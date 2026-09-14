"""
blueprints/api.py — Clean JSON REST API for GovRecruitmentTracker.

Endpoints:
  - GET  /api/jobs                List jobs with search, filtering, and pagination
  - GET  /api/jobs/<id>           Get full details of a specific job
  - POST /api/jobs/<id>/status    Update tracking status, notes, or registration numbers
  - GET  /api/metrics             Summary KPI metrics (Total, Non-GATE, Applied, Synced)
  - GET  /api/sources             List all configured government recruitment sources
  - POST /api/fetch-now           Trigger background scraper pipeline
  - GET  /api/health              System health check endpoint
"""

from __future__ import annotations

import html
import logging
import threading
from typing import Any

from flask import Blueprint, current_app, jsonify, request
import requests
from sqlalchemy import or_

from models import Job, Source, UserStatus, db

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)

# ── Admit Card & Hall Ticket Detection Keywords ─────────────────────────────
ADMIT_CARD_KEYWORDS: list[str] = [
    "admit card",
    "hall ticket",
    "call letter",
    "e-admit",
    "city intimation",
    "exam city slip",
    "written examination schedule",
    "download admit",
    "cbt schedule",
    "examination schedule",
]


def scan_for_admit_card(url: str, session: requests.Session | None = None) -> tuple[bool, str]:
    """
    Fetch URL content and detect if Admit Card / Exam City has been published.
    Returns (detected: bool, matched_keyword: str).
    """
    if not url or not url.startswith("http"):
        return False, ""

    s = session or requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        resp = s.get(url, headers=headers, timeout=10, verify=True)
    except requests.exceptions.SSLError:
        try:
            resp = s.get(url, headers=headers, timeout=10, verify=False)
        except Exception:
            return False, ""
    except Exception:
        return False, ""

    if resp.status_code != 200:
        return False, ""

    content = resp.text.lower()
    for kw in ADMIT_CARD_KEYWORDS:
        if kw in content:
            return True, kw

    return False, ""


def check_applied_jobs_admit_cards(session: requests.Session | None = None) -> list[dict[str, Any]]:
    """
    Check all jobs with status 'Applied' for newly released Admit Cards / Hall Tickets.
    If detected, automatically updates status to 'Admit Card Out' and fires a Telegram alert.
    """
    applied_jobs = Job.query.filter(Job.application_status == UserStatus.APPLIED).all()
    detected_list: list[dict[str, Any]] = []

    for job in applied_jobs:
        url_to_check = job.notification_url or job.pdf_url
        found, keyword = scan_for_admit_card(url_to_check, session=session)
        if found:
            job.application_status = UserStatus.ADMIT_CARD_OUT
            timestamp_note = f"\n[Auto-Detected]: Admit card announcement ('{keyword}') found on portal."
            job.notes = (job.notes or "") + timestamp_note
            db.session.add(job)

            # Fire Telegram Notification
            try:
                from telegram_notifier import send_message_async
                msg = (
                    f"🚨 <b>Admit Card / Hall Ticket Alert!</b>\n\n"
                    f"🏛️ <b>{html.escape(job.organization)}</b>\n"
                    f"📌 <b>{html.escape(job.title)}</b>\n\n"
                    f"Admit card / exam announcement (keyword: <i>{html.escape(keyword)}</i>) "
                    f"was detected on the official portal!\n"
                    f"Application status updated to: <b>Admit Card Out</b>\n\n"
                )
                if job.registration_number:
                    msg += f"🆔 <b>Your Registration ID:</b> <code>{html.escape(job.registration_number)}</code>\n"
                if job.notification_url:
                    msg += f'<a href="{html.escape(job.notification_url)}">🌐 Visit Official Portal</a>'

                send_message_async(msg)
            except Exception as e:
                logger.warning("Failed to send Admit Card Telegram alert: %s", e)

            detected_list.append({
                "job_id": job.id,
                "title": job.title,
                "organization": job.organization,
                "keyword": keyword,
                "url": job.notification_url,
            })

    if detected_list:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    return detected_list



@api_bp.route("/health", methods=["GET"])
def health_check():
    """Service health check."""
    return jsonify({
        "status": "healthy",
        "service": "GovRecruitmentTracker",
        "version": "1.0.0",
    })


@api_bp.route("/metrics", methods=["GET"])
def get_metrics():
    """Retrieve top-level KPI metrics."""
    try:
        from blueprints.dashboard import compute_metrics
        return jsonify({"status": "success", "metrics": compute_metrics()})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@api_bp.route("/jobs", methods=["GET"])
def list_jobs():
    """
    List jobs with optional filtering.

    Query parameters:
      - category: ExamCategory filter (or 'all')
      - gate: 'all' | 'gate_only' | 'non_gate'
      - status: UserStatus filter (or 'all')
      - search: Text query searching title, org, qualifications
      - limit: Max records to return (default: 50, max: 200)
      - offset: Pagination offset (default: 0)
    """
    category = request.args.get("category", "all").strip()
    gate = request.args.get("gate", "all").strip()
    status = request.args.get("status", "all").strip()
    search = request.args.get("search", "").strip()

    try:
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        limit = 50
        offset = 0

    query = Job.query

    if category != "all" and category:
        query = query.filter(Job.exam_category == category)

    if gate == "gate_only":
        query = query.filter(Job.gate_required == True)
    elif gate == "non_gate":
        query = query.filter(Job.gate_required == False)

    if status != "all" and status:
        query = query.filter(Job.user_status == status)

    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                Job.title.ilike(search_pattern),
                Job.organization.ilike(search_pattern),
                Job.educational_qualifications.ilike(search_pattern),
            )
        )

    total_count = query.count()
    jobs = query.order_by(Job.last_date.asc(), Job.id.desc()).offset(offset).limit(limit).all()

    return jsonify({
        "status": "success",
        "total": total_count,
        "count": len(jobs),
        "offset": offset,
        "limit": limit,
        "jobs": [j.to_dict() for j in jobs],
    })


@api_bp.route("/jobs/<int:job_id>", methods=["GET"])
def get_job_detail(job_id: int):
    """Retrieve full details of a specific job."""
    job = Job.query.get_or_404(job_id)
    return jsonify({"status": "success", "job": job.to_dict()})


@api_bp.route("/jobs/<int:job_id>/status", methods=["POST"])
def update_job_status(job_id: int):
    """Update status, notes, or registration numbers for a job via JSON."""
    job = Job.query.get_or_404(job_id)
    data = request.get_json(silent=True) or {}

    new_status = data.get("user_status")
    if new_status:
        new_status = new_status.strip()
        if new_status in UserStatus.ALL:
            job.user_status = new_status
        else:
            return jsonify({
                "status": "error",
                "message": f"Invalid status '{new_status}'. Allowed: {UserStatus.ALL}",
            }), 400

    if "notes" in data:
        job.notes = str(data["notes"]).strip()
    if "registration_number" in data:
        job.registration_number = str(data["registration_number"]).strip()
    if "roll_number" in data:
        job.roll_number = str(data["roll_number"]).strip()

    try:
        db.session.commit()
        return jsonify({
            "status": "success",
            "message": "Job status updated",
            "job": job.to_dict(),
        })
    except Exception as exc:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(exc)}), 500


@api_bp.route("/sources", methods=["GET"])
def list_sources():
    """List all configured recruitment sources."""
    sources = Source.query.order_by(Source.name.asc()).all()
    return jsonify({
        "status": "success",
        "total": len(sources),
        "sources": [s.to_dict() for s in sources],
    })


@api_bp.route("/fetch-now", methods=["POST"])
def trigger_fetch():
    """Trigger the scraper pipeline in a non-blocking background thread."""
    from blueprints.jobs import _run_fetch_in_background

    app = current_app._get_current_object()  # type: ignore[attr-defined]
    thread = threading.Thread(
        target=_run_fetch_in_background,
        args=(app,),
        name="api-bg-fetch",
        daemon=True,
    )
    thread.start()

    return jsonify({
        "status": "started",
        "message": "Background recruitment scraper dispatched.",
    }), 202


@api_bp.route("/cron/sync", methods=["GET", "POST"])
def cron_sync():
    """
    Automated cron trigger endpoint for cloud schedulers (e.g. cron-job.org, GitHub Actions).

    Security:
      - Requires authentication via ?token=..., X-Cron-Token header, or Authorization: Bearer <token>.
      - Validates against CRON_TOKEN or SECRET_KEY.

    Actions:
      1. Awakens the server from cloud sleep mode.
      2. Dispatches autonomous background scraping across all active portals.
      3. Scans official notices of 'Applied' jobs for Admit Card / Hall Ticket releases.
      4. Dispatches real-time Telegram alerts and updates application status to 'Admit Card Out'.
    """
    token = request.args.get("token") or request.headers.get("X-Cron-Token")
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

    expected_token = current_app.config.get("CRON_TOKEN") or current_app.config.get("SECRET_KEY")
    if not token or token != expected_token:
        return jsonify({
            "status": "error",
            "message": "Unauthorized: invalid or missing cron token",
        }), 401

    # 1. Dispatch Background Scraper
    from blueprints.jobs import _run_fetch_in_background
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    thread = threading.Thread(
        target=_run_fetch_in_background,
        args=(app,),
        name="cron-bg-fetch",
        daemon=True,
    )
    thread.start()

    # 2. Check Admit Cards for Applied Jobs
    detected_cards = check_applied_jobs_admit_cards()

    return jsonify({
        "status": "success",
        "message": "Cron synchronization triggered successfully.",
        "scrapers_dispatched": True,
        "admit_cards_checked": Job.query.filter(Job.application_status.in_([UserStatus.APPLIED, UserStatus.ADMIT_CARD_OUT])).count(),
        "admit_cards_detected": detected_cards,
        "newly_detected_count": len(detected_cards),
    }), 200

