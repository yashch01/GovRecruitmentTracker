"""
blueprints/dashboard.py — Main dashboard blueprint for GovRecruitmentTracker.

Handles:
  - KPI Metrics (Total, Non-GATE CS/IT, Competitive Exams, Applied, Calendar Synced)
  - Multi-dimensional Filtering:
      • Exam category (Technical CS/IT, Competitive Exam, PSU, Banking, Military, Other)
      • GATE requirement (All, GATE Only, Non-GATE)
      • Application status (Not Applied, Applied, Admit Card Out, Exam Done, Selected)
      • Urgency (Urgent <7 days, Moderate 7-30 days, Relaxed >30 days, Expired)
      • Full-text search (Title, Organization, Qualifications, Notes)
  - Sort ordering (Deadline ascending/descending, Date added, Org)
  - Responsive HTML rendering and JSON format support.
"""

from __future__ import annotations

from datetime import date
import logging

from flask import Blueprint, Response, jsonify, render_template, request
from sqlalchemy import or_

from calendar_sync import generate_ical_feed, parse_date
from models import ExamCategory, Job, UserStatus

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)


def compute_metrics() -> dict[str, int]:
    """Compute top-level KPI metrics for stat cards."""
    try:
        total_jobs = Job.query.count()
        non_gate_cs_it = Job.query.filter(
            Job.exam_category == ExamCategory.TECHNICAL_CS_IT,
            Job.gate_required == False,
        ).count()
        competitive_exams = Job.query.filter(
            Job.exam_category.in_([
                ExamCategory.COMPETITIVE_EXAM,
                ExamCategory.BANKING,
                ExamCategory.MILITARY,
                ExamCategory.PSU,
            ])
        ).count()
        applied_count = Job.query.filter(
            Job.application_status.in_([
                UserStatus.APPLIED,
                UserStatus.ADMIT_CARD_OUT,
                UserStatus.EXAM_DONE,
                UserStatus.SELECTED,
            ])
        ).count()
        synced_count = Job.query.filter(Job.is_synced_to_calendar == True).count()

        return {
            "total_jobs": total_jobs,
            "non_gate_cs_it": non_gate_cs_it,
            "competitive_exams": competitive_exams,
            "applied_count": applied_count,
            "synced_count": synced_count,
        }
    except Exception as exc:
        logger.error("Error computing metrics: %s", exc)
        return {
            "total_jobs": 0,
            "non_gate_cs_it": 0,
            "competitive_exams": 0,
            "applied_count": 0,
            "synced_count": 0,
        }


def calculate_urgency(last_date_str: str | None) -> tuple[str, int | None]:
    """
    Given a last_date string, return (urgency_label, days_remaining).
    Urgency labels: 'urgent' (<7d), 'moderate' (7-30d), 'relaxed' (>30d), 'expired' (<0d), 'unknown'.
    """
    if not last_date_str:
        return "unknown", None

    parsed = parse_date(last_date_str)
    if not parsed:
        return "unknown", None

    today = date.today()
    delta_days = (parsed - today).days

    if delta_days < 0:
        return "expired", delta_days
    elif delta_days <= 7:
        return "urgent", delta_days
    elif delta_days <= 30:
        return "moderate", delta_days
    else:
        return "relaxed", delta_days


@dashboard_bp.route("/")
def index():
    """Main dashboard page."""
    # ── Read Query Parameters ────────────────────────────────────────────────
    category = request.args.get("category", "all").strip()
    gate = request.args.get("gate", "all").strip()
    status = request.args.get("status", "all").strip()
    urgency = request.args.get("urgency", "all").strip()
    search = request.args.get("search", "").strip()
    sort_by = request.args.get("sort", "deadline_asc").strip()

    # ── Base Query ───────────────────────────────────────────────────────────
    query = Job.query

    # Category Filter
    if category != "all" and category:
        query = query.filter(Job.exam_category == category)

    # GATE Filter
    if gate == "gate_only":
        query = query.filter(Job.gate_required == True)
    elif gate == "non_gate":
        query = query.filter(Job.gate_required == False)

    # Status Filter
    if status != "all" and status:
        query = query.filter(Job.application_status == status)

    # Search Query
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                Job.title.ilike(search_pattern),
                Job.organization.ilike(search_pattern),
                Job.educational_qualifications.ilike(search_pattern),
                Job.notes.ilike(search_pattern),
            )
        )

    # Sort Ordering
    if sort_by == "date_added_desc":
        query = query.order_by(Job.created_at.desc())
    elif sort_by == "org_asc":
        query = query.order_by(Job.organization.asc())
    elif sort_by == "deadline_desc":
        query = query.order_by(Job.last_date.desc())
    else:  # deadline_asc default
        query = query.order_by(Job.last_date.asc(), Job.id.desc())

    jobs = query.all()

    # Filter by urgency in Python (dates stored as varying strings)
    if urgency != "all" and urgency:
        filtered_jobs = []
        for j in jobs:
            label, _ = calculate_urgency(j.last_date)
            if label == urgency:
                filtered_jobs.append(j)
        jobs = filtered_jobs

    # Enrich jobs with urgency info for templates
    for j in jobs:
        label, days = calculate_urgency(j.last_date)
        setattr(j, "urgency_label", label)
        setattr(j, "days_remaining", days)

    metrics = compute_metrics()

    # JSON response if requested
    if request.is_json or request.headers.get("Accept") == "application/json":
        return jsonify({
            "metrics": metrics,
            "jobs_count": len(jobs),
            "jobs": [j.to_dict() for j in jobs],
            "filters": {
                "category": category,
                "gate": gate,
                "status": status,
                "urgency": urgency,
                "search": search,
                "sort": sort_by,
            },
        })

    return render_template(
        "dashboard.html",
        jobs=jobs,
        metrics=metrics,
        current_category=category,
        current_gate=gate,
        current_status=status,
        current_urgency=urgency,
        current_search=search,
        current_sort=sort_by,
        categories=ExamCategory.ALL,
        statuses=UserStatus.ALL,
    )


@dashboard_bp.route("/calendar.ics")
@dashboard_bp.route("/calendar/feed.ics")
def ical_feed():
    """
    Return dynamic RFC 5545 iCalendar feed (.ics) containing all tracked recruitment deadlines.

    Compatible with Apple Calendar (iOS/macOS), Google Calendar, Outlook, and Thunderbird.
    Includes separate deadline & exam events with 3-day and 1-day reminders.
    """
    jobs = Job.query.order_by(Job.id.desc()).all()
    ical_content = generate_ical_feed(jobs)
    return Response(
        ical_content,
        mimetype="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": "inline; filename=recruitment_deadlines.ics",
            "Cache-Control": "public, max-age=1800",
        },
    )

