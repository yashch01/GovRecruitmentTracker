"""
blueprints/jobs.py — Job management, status tracking, calendar sync, and async scrapers.

Features:
  - Update user application status (Not Applied, Applied, Admit Card, Exam Done, Selected)
  - Edit personal tracking notes, registration numbers, and roll numbers
  - Non-blocking /fetch-now background scraper trigger via daemon threading
  - Trigger Google Calendar sync (bulk or single job)
  - Trigger Telegram notification for individual jobs
  - Delete tracked jobs and clean up calendar entries
"""

from __future__ import annotations

import logging
import threading

from flask import Blueprint, current_app, flash, jsonify, redirect, request, url_for

import calendar_sync
from models import Job, Source, UserStatus, db
import telegram_notifier

logger = logging.getLogger(__name__)

jobs_bp = Blueprint("jobs", __name__)


# ── Background Scraper Worker ────────────────────────────────────────────────
def _run_fetch_in_background(app) -> None:
    """
    Background worker executed in a daemon thread.
    Executes the scraper pipeline within the Flask application context.
    """
    with app.app_context():
        try:
            from parser import run_extraction_pipeline
            from scrapers.portal_scraper import run_scraper_pipeline

            active_sources = Source.query.filter_by(is_active=True).all()
            if not active_sources:
                logger.info("[Async Fetch] No active sources found to scrape.")
                return

            archives_dir = app.config.get("ARCHIVES_DIR", "archives")

            def _handle_scraped_items(items: list[dict]) -> None:
                """Callback invoked per scraper when notices are scraped."""
                for item in items:
                    try:
                        url = item.get("notification_url", "")
                        title = item.get("title", "")
                        org = item.get("organization", "")
                        pdf_url = item.get("pdf_url", "")
                        archive_path = item.get("archive_path", "")

                        # Check if already exists in DB
                        existing = Job.query.filter_by(notification_url=url).first() if url else None
                        if existing:
                            continue

                        # Extract details if text or PDF available
                        text_content = item.get("text_content", "") or title
                        extracted = run_extraction_pipeline(
                            raw_text=text_content,
                            pdf_path=archive_path or None,
                            gemini_api_key=app.config.get("GEMINI_API_KEY", ""),
                        )

                        # Classification & CS/IT eligibility check
                        cat = extracted.get("exam_category", item.get("exam_category", "Other"))
                        is_cs = extracted.get("eligible_cs_it", True)

                        new_job = Job(
                            title=extracted.get("title") or title or "Recruitment Notification",
                            organization=extracted.get("organization") or org or "Government of India",
                            notification_url=url,
                            pdf_url=pdf_url or extracted.get("pdf_url", ""),
                            pdf_archive_path=archive_path,
                            eligible_cs_it=is_cs,
                            gate_required=extracted.get("gate_required", False),
                            exam_category=cat,
                            pay_level_or_ctc=extracted.get("pay_level_or_ctc", ""),
                            educational_qualifications=extracted.get("educational_qualifications", ""),
                            age_limit_details=extracted.get("age_limit_details", ""),
                            selection_summary=extracted.get("selection_summary", ""),
                            last_date=extracted.get("last_date", ""),
                            exam_date=extracted.get("exam_date", ""),
                            source_id=item.get("source_id"),
                        )
                        db.session.add(new_job)
                        db.session.commit()

                        # Dispatch Telegram alert non-blockingly
                        telegram_notifier.notify_new_job(new_job, async_send=True)
                        logger.info("[Async Fetch] Saved new job #%d: %s (%s)", new_job.id, new_job.title, new_job.organization)

                    except Exception as exc:
                        db.session.rollback()
                        logger.error("[Async Fetch] Error saving scraped item: %s", exc)

            logger.info("[Async Fetch] Starting scraper pipeline for %d active sources...", len(active_sources))
            run_scraper_pipeline(
                sources=active_sources,
                on_result=_handle_scraped_items,
                blocking=True,
                archives_dir=archives_dir,
            )
            logger.info("[Async Fetch] Scraper pipeline finished successfully.")

        except Exception as exc:
            logger.error("[Async Fetch] Fatal error in background fetch worker: %s", exc)


# ── Routes ───────────────────────────────────────────────────────────────────

@jobs_bp.route("/fetch-now", methods=["POST"])
def fetch_now():
    """
    Trigger scraper pipeline in a non-blocking background daemon thread.
    Returns HTTP 202 immediately to prevent web requests from timing out.
    """
    app = current_app._get_current_object()  # type: ignore[attr-defined]
    thread = threading.Thread(
        target=_run_fetch_in_background,
        args=(app,),
        name="bg-scraper-fetch",
        daemon=True,
    )
    thread.start()

    message = "Scraper pipeline triggered in background. New notices will appear as they are processed."
    if request.is_json or request.headers.get("Accept") == "application/json":
        return jsonify({"status": "started", "message": message}), 202

    flash(message, "info")
    return redirect(request.referrer or url_for("dashboard.index"))


@jobs_bp.route("/jobs/<int:job_id>", methods=["GET"])
def get_job(job_id: int):
    """Retrieve details for a single job."""
    job = Job.query.get_or_404(job_id)
    if request.is_json or request.headers.get("Accept") == "application/json":
        return jsonify({"status": "success", "job": job.to_dict()})
    return jsonify(job.to_dict())


@jobs_bp.route("/jobs/<int:job_id>/status", methods=["POST"])
def update_status(job_id: int):
    """Update application tracking status, notes, or registration numbers."""
    job = Job.query.get_or_404(job_id)

    data = request.get_json(silent=True) or request.form.to_dict()

    new_status = data.get("user_status")
    if new_status:
        new_status = new_status.strip()
        if new_status in UserStatus.ALL:
            job.user_status = new_status
        else:
            return jsonify({"status": "error", "message": f"Invalid status: {new_status}"}), 400

    if "notes" in data:
        job.notes = data.get("notes", "").strip()
    if "registration_number" in data:
        job.registration_number = data.get("registration_number", "").strip()
    if "roll_number" in data:
        job.roll_number = data.get("roll_number", "").strip()

    try:
        db.session.commit()
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "success", "message": "Status updated", "job": job.to_dict()})
        flash(f"Updated status for {job.organization} — {job.title}", "success")
        return redirect(request.referrer or url_for("dashboard.index"))
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to update job status #%d: %s", job_id, exc)
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": str(exc)}), 500
        flash("Failed to update status", "error")
        return redirect(request.referrer or url_for("dashboard.index"))


@jobs_bp.route("/sync-calendar", methods=["POST"])
def sync_calendar_all():
    """Sync all unsynced jobs with dates to Google Calendar."""
    jobs = Job.query.filter(
        db.or_(Job.last_date != "", Job.exam_date != "")
    ).all()

    summary = calendar_sync.sync_all_jobs(jobs)
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning("DB commit failed after bulk calendar sync: %s", exc)

    if request.is_json or request.headers.get("Accept") == "application/json":
        return jsonify({"status": "success", "summary": summary})

    flash(
        f"Calendar sync complete: {summary['synced']} synced, {summary['skipped']} skipped, {summary['errors']} errors.",
        "success" if summary["errors"] == 0 else "warning",
    )
    return redirect(request.referrer or url_for("dashboard.index"))


@jobs_bp.route("/jobs/<int:job_id>/sync-calendar", methods=["POST"])
def sync_calendar_single(job_id: int):
    """Sync an individual job to Google Calendar."""
    job = Job.query.get_or_404(job_id)
    res = calendar_sync.sync_job_to_calendar(job)

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning("DB commit failed after calendar sync: %s", exc)

    if res.get("error"):
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": res["error"]}), 400
        flash(f"Calendar sync error: {res['error']}", "error")
    else:
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "success", "result": res})
        flash(f"Job #{job_id} successfully synced to Google Calendar!", "success")

    return redirect(request.referrer or url_for("dashboard.index"))


@jobs_bp.route("/jobs/<int:job_id>/notify-telegram", methods=["POST"])
def notify_telegram_single(job_id: int):
    """Send an immediate Telegram alert for a specific job."""
    job = Job.query.get_or_404(job_id)
    ok = telegram_notifier.notify_new_job(job, async_send=False)

    if ok:
        msg = f"Telegram alert delivered for {job.organization} — {job.title}!"
        status = "success"
    else:
        msg = "Telegram alert failed. Please check your bot token and chat ID in Settings."
        status = "error"

    if request.is_json or request.headers.get("Accept") == "application/json":
        return jsonify({"status": status, "message": msg}), (200 if ok else 400)

    flash(msg, status)
    return redirect(request.referrer or url_for("dashboard.index"))


@jobs_bp.route("/jobs/<int:job_id>/delete", methods=["POST"])
def delete_job(job_id: int):
    """Delete a tracked job and clean up its calendar events."""
    job = Job.query.get_or_404(job_id)
    try:
        calendar_sync.delete_job_events(job.id)
        db.session.delete(job)
        db.session.commit()
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "success", "message": f"Job #{job_id} deleted"})
        flash(f"Job #{job_id} deleted successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        logger.error("Error deleting job #%d: %s", job_id, exc)
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": str(exc)}), 500
        flash(f"Failed to delete job: {exc}", "error")

    return redirect(request.referrer or url_for("dashboard.index"))
