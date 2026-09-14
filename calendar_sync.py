"""
calendar_sync.py — Google Calendar sync for GovRecruitmentTracker.

Architecture
------------
  - One Calendar event per job (individual, never grouped).
  - Events are keyed by an extendedProperty ``grt_job_id`` so re-syncing
    is idempotent — existing events are updated in-place, never duplicated.
  - Two event types per job (both optional):
      • Deadline event  — all-day on last_date  (registration close)
      • Exam event      — all-day on exam_date  (written test)
  - Three popup reminders: 7 days, 3 days, 1 day before.
  - Colour-coded by exam_category (see CATEGORY_COLOUR_MAP).
  - Falls back gracefully when credentials are missing — logs a warning
    and returns without crashing the rest of the pipeline.

OAuth2 Setup (one-time)
-----------------------
  1. Google Cloud Console → enable Calendar API.
  2. Create OAuth2 Desktop credentials → download as credentials.json.
  3. python calendar_sync.py --setup  (writes token.json, reused afterwards).

Environment variables
---------------------
  GOOGLE_CREDENTIALS_FILE  Path to credentials.json  (default: credentials.json)
  GOOGLE_TOKEN_FILE        Path to token.json        (default: token.json)
  GOOGLE_CALENDAR_ID       Target calendar ID        (default: primary)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Calendar API scope ────────────────────────────────────────────────────────
_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# ── File paths (overridable via env) ─────────────────────────────────────────
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE       = os.environ.get("GOOGLE_TOKEN_FILE",       "token.json")
CALENDAR_ID      = os.environ.get("GOOGLE_CALENDAR_ID",      "primary")

# ── Colour map: Google Calendar colorId (1-11) by exam category ──────────────
CATEGORY_COLOUR_MAP: dict[str, str] = {
    "Technical CS/IT":  "2",   # Sage green
    "PSU":              "5",   # Banana yellow
    "Competitive Exam": "7",   # Peacock teal
    "Banking":          "9",   # Blueberry
    "Military":         "11",  # Tomato red
    "Other":            "8",   # Graphite
}

# ── Extended property key linking Calendar events to Job rows ─────────────────
_PROP_KEY = "grt_job_id"


# ============================================================================
# Date parsing helpers
# ============================================================================

_DATE_FORMATS = [
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
]


def parse_date(date_str: str) -> date | None:
    """
    Parse a date string in multiple Indian govt notice formats.
    Returns datetime.date or None on failure.
    """
    if not date_str or not date_str.strip():
        return None
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str.strip(), flags=re.I)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    # Last-resort: extract YYYY-MM-DD substring
    m = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2})", cleaned)
    if m:
        try:
            return datetime.strptime(m.group(1).replace("/", "-"), "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


# ============================================================================
# OAuth2 / credentials
# ============================================================================

def _load_credentials():
    """Load and auto-refresh Google OAuth2 credentials. Returns None if unavailable."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        logger.error("google-auth not installed.")
        return None

    creds = None
    token_path = Path(TOKEN_FILE)
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
        except Exception as exc:
            logger.warning("Failed to load token.json: %s", exc)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            Path(TOKEN_FILE).write_text(creds.to_json())
            logger.info("Google credentials refreshed.")
        except Exception as exc:
            logger.error("Failed to refresh credentials: %s", exc)
            return None

    if not creds or not creds.valid:
        logger.warning(
            "Google Calendar credentials not configured. "
            "Run: python calendar_sync.py --setup"
        )
        return None

    return creds


def run_oauth_setup() -> bool:
    """Interactive OAuth2 setup flow. Run once from CLI to write token.json."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        logger.error("google-auth-oauthlib not installed.")
        return False

    creds_path = Path(CREDENTIALS_FILE)
    if not creds_path.exists():
        print(f"credentials.json not found at {creds_path.resolve()}")
        return False

    try:
        flow  = InstalledAppFlow.from_client_secrets_file(str(creds_path), _SCOPES)
        creds = flow.run_local_server(port=0)
        Path(TOKEN_FILE).write_text(creds.to_json())
        print(f"Authorised. token.json written to {Path(TOKEN_FILE).resolve()}")
        return True
    except Exception as exc:
        logger.error("OAuth2 setup failed: %s", exc)
        return False


# ============================================================================
# Calendar service builder
# ============================================================================

def _build_service():
    """Return an authenticated Google Calendar API service, or None."""
    creds = _load_credentials()
    if creds is None:
        return None
    try:
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:
        logger.error("Failed to build Calendar service: %s", exc)
        return None


# ============================================================================
# Event body construction
# ============================================================================

def build_event_body(job: Any, event_date: date, event_type: str = "deadline") -> dict:
    """
    Build a Google Calendar event dict for a single job.

    Args:
        job:        Job ORM row (any object with the expected attributes).
        event_date: The date for this event.
        event_type: "deadline" (registration close) | "exam" (written test).
    """
    if event_type == "exam":
        emoji, label = "📝", "EXAM"
    else:
        emoji, label = "🚨", "LAST DATE"

    cs_suffix = " (CS/IT)" if getattr(job, "eligible_cs_it", False) else ""
    title = f"{emoji} {label}: {job.organization} — {job.title}{cs_suffix}"
    if len(title) > 100:
        title = title[:97] + "…"

    lines = [
        f"Organisation:   {job.organization}",
        f"Post/Exam:      {job.title}",
        f"Category:       {job.exam_category}",
    ]
    if getattr(job, "pay_level_or_ctc", ""):
        lines.append(f"Pay:            {job.pay_level_or_ctc}")
    if getattr(job, "last_date", ""):
        lines.append(f"Last Date:      {job.last_date}")
    if getattr(job, "exam_date", ""):
        lines.append(f"Exam Date:      {job.exam_date}")
    if getattr(job, "age_limit_details", ""):
        lines.append(f"Age Limit:      {job.age_limit_details}")
    if getattr(job, "selection_summary", ""):
        lines.append(f"Selection:      {job.selection_summary}")
    lines.append("")
    if getattr(job, "notification_url", ""):
        lines.append(f"Notice:  {job.notification_url}")
    if getattr(job, "pdf_url", ""):
        lines.append(f"PDF:     {job.pdf_url}")
    lines.append(f"\nTracked by GovRecruitmentTracker (Job ID #{job.id})")

    color_id = CATEGORY_COLOUR_MAP.get(getattr(job, "exam_category", "Other"), "8")

    return {
        "summary":     title,
        "description": "\n".join(lines),
        "colorId":     color_id,
        "start": {"date": event_date.isoformat()},
        "end":   {"date": (event_date + timedelta(days=1)).isoformat()},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 7 * 24 * 60},
                {"method": "popup", "minutes": 3 * 24 * 60},
                {"method": "popup", "minutes": 1 * 24 * 60},
            ],
        },
        "extendedProperties": {
            "private": {
                _PROP_KEY:          str(job.id),
                "grt_event_type":   event_type,
                "grt_organization": getattr(job, "organization", "")[:100],
            }
        },
    }


# ============================================================================
# Core CRUD
# ============================================================================

def _find_existing_event(service, job_id: int, event_type: str) -> str | None:
    """Find existing Calendar event for job_id+event_type. Returns event ID or None."""
    try:
        result = service.events().list(
            calendarId=CALENDAR_ID,
            privateExtendedProperty=f"{_PROP_KEY}={job_id}",
            maxResults=10,
            singleEvents=True,
        ).execute()
        for ev in result.get("items", []):
            props = ev.get("extendedProperties", {}).get("private", {})
            if props.get(_PROP_KEY) == str(job_id) and props.get("grt_event_type") == event_type:
                return ev["id"]
    except Exception as exc:
        logger.warning("Error searching Calendar events (job=%d): %s", job_id, exc)
    return None


def _upsert_event(service, job: Any, event_date: date, event_type: str) -> str | None:
    """
    Create or update a single Calendar event.
    Returns the event ID on success, None on failure.
    """
    body        = build_event_body(job, event_date, event_type)
    existing_id = _find_existing_event(service, job.id, event_type)
    try:
        if existing_id:
            ev = service.events().update(
                calendarId=CALENDAR_ID, eventId=existing_id, body=body
            ).execute()
            logger.info("[Calendar] Updated %s event %s (job #%d)", event_type, ev["id"], job.id)
        else:
            ev = service.events().insert(
                calendarId=CALENDAR_ID, body=body
            ).execute()
            logger.info("[Calendar] Created %s event %s (job #%d)", event_type, ev["id"], job.id)
        return ev["id"]
    except Exception as exc:
        logger.error("[Calendar] Failed to upsert %s event (job #%d): %s", event_type, job.id, exc)
        return None


def sync_job_to_calendar(job: Any, service: Any = None) -> dict[str, str | None]:
    """
    Sync a single job to Google Calendar.
    Creates/updates up to two events: deadline + exam.

    Returns:
        {"deadline_event_id": str|None, "exam_event_id": str|None, "error": str|None}
    """
    result: dict[str, str | None] = {
        "deadline_event_id": None,
        "exam_event_id":     None,
        "error":             None,
    }

    if service is None:
        service = _build_service()
    if service is None:
        result["error"] = "Calendar service unavailable"
        return result

    deadline = parse_date(getattr(job, "last_date", "") or "")
    if deadline:
        result["deadline_event_id"] = _upsert_event(service, job, deadline, "deadline")
        if result["deadline_event_id"] is None:
            result["error"] = "Failed to sync deadline event"

    exam_dt = parse_date(getattr(job, "exam_date", "") or "")
    if exam_dt:
        result["exam_event_id"] = _upsert_event(service, job, exam_dt, "exam")
        if result["exam_event_id"] is None and not result["error"]:
            result["error"] = "Failed to sync exam event"

    if result["deadline_event_id"] or result["exam_event_id"]:
        if hasattr(job, "is_synced_to_calendar"):
            job.is_synced_to_calendar = True
        if hasattr(job, "calendar_event_id"):
            job.calendar_event_id = result["deadline_event_id"] or result["exam_event_id"] or ""

    return result


def delete_job_events(job_id: int, service: Any = None) -> int:
    """Delete all Calendar events for a job. Returns count deleted."""
    if service is None:
        service = _build_service()
    if service is None:
        return 0

    deleted = 0
    for event_type in ("deadline", "exam"):
        ev_id = _find_existing_event(service, job_id, event_type)
        if ev_id:
            try:
                service.events().delete(calendarId=CALENDAR_ID, eventId=ev_id).execute()
                deleted += 1
                logger.info("[Calendar] Deleted %s event %s (job #%d)", event_type, ev_id, job_id)
            except Exception as exc:
                logger.error("[Calendar] Delete failed for event %s: %s", ev_id, exc)

    return deleted


def sync_all_jobs(jobs: list[Any], service: Any = None) -> dict[str, int]:
    """
    Sync a list of Job ORM rows. Returns {"synced": N, "skipped": N, "errors": N}.
    """
    summary = {"synced": 0, "skipped": 0, "errors": 0}
    if not jobs:
        return summary

    if service is None:
        service = _build_service()
    if service is None:
        summary["skipped"] = len(jobs)
        return summary

    for job in jobs:
        has_date = getattr(job, "last_date", "") or getattr(job, "exam_date", "")
        if not has_date:
            summary["skipped"] += 1
            continue
        res = sync_job_to_calendar(job, service=service)
        if res.get("error") and not res.get("deadline_event_id") and not res.get("exam_event_id"):
            summary["errors"] += 1
        else:
            summary["synced"] += 1

    logger.info("[Calendar] Bulk sync done: %s", summary)
    return summary


def is_calendar_configured() -> bool:
    """Return True if a valid token.json exists on disk."""
    token_path = Path(TOKEN_FILE)
    if not token_path.exists():
        return False
    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
        return creds is not None
    except Exception:
        return False


def _escape_ical(text: str) -> str:
    """Escape characters for RFC 5545 iCalendar values."""
    if not text:
        return ""
    res = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    res = res.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return res


def generate_ical_feed(jobs: list[Any], calendar_name: str = "Gov Recruitment Deadlines") -> str:
    """
    Generate an RFC 5545 compliant .ics iCalendar subscription feed.

    Features:
      - Individual event per recruitment deadline with 3-day and 1-day reminders.
      - Separate event per exam date with 7-day and 1-day reminders.
      - Works with Apple Calendar (iOS/macOS), Google Calendar, Outlook, and Thunderbird.
    """
    now_utc = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//GovRecruitmentTracker//Recruitment Deadlines//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_ical(calendar_name)}",
        "X-WR-TIMEZONE:Asia/Kolkata",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]

    for job in jobs:
        title = getattr(job, "title", "") or "Recruitment Notification"
        org = getattr(job, "organization", "") or "Gov Org"
        job_id = getattr(job, "id", "0")
        last_date_str = getattr(job, "last_date", "") or ""
        exam_date_str = getattr(job, "exam_date", "") or ""
        pay = getattr(job, "pay_level_or_ctc", "") or "Standard Gov"
        cat = getattr(job, "exam_category", "") or "Other"
        url = getattr(job, "notification_url", "") or getattr(job, "pdf_url", "") or ""
        notes = getattr(job, "notes", "") or ""
        gate = "Yes (GATE Required)" if getattr(job, "gate_required", False) else "No (Direct / Non-GATE)"
        status = getattr(job, "user_status", "") or getattr(job, "application_status", "Not Applied")
        reg_num = getattr(job, "registration_number", "") or ""

        # 1. Registration Deadline Event
        deadline_date = parse_date(last_date_str)
        if deadline_date:
            dt_start = deadline_date.strftime("%Y%m%d")
            dt_end = (deadline_date + timedelta(days=1)).strftime("%Y%m%d")

            desc_parts = [
                f"Organisation: {org}",
                f"Post: {title}",
                f"Exam Category: {cat}",
                f"Pay Scale: {pay}",
                f"GATE Requirement: {gate}",
                f"Application Status: {status}",
            ]
            if reg_num:
                desc_parts.append(f"Registration ID: {reg_num}")
            if notes:
                desc_parts.append(f"Notes: {notes}")
            if url:
                desc_parts.append(f"Official Notice URL: {url}")

            desc_str = _escape_ical("\n".join(desc_parts))
            summary_str = _escape_ical(f"📌 Last Date: {org} — {title}")

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:grt-job-{job_id}-deadline@govrecruitmenttracker",
                f"DTSTAMP:{now_utc}",
                f"DTSTART;VALUE=DATE:{dt_start}",
                f"DTEND;VALUE=DATE:{dt_end}",
                f"SUMMARY:{summary_str}",
                f"DESCRIPTION:{desc_str}",
                f"CATEGORIES:{_escape_ical(str(cat))}",
                "STATUS:CONFIRMED",
            ])
            if url:
                lines.append(f"URL:{url}")

            lines.extend([
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape_ical(f'Reminder: 3 days remaining to apply for {org} — {title}')}",
                "TRIGGER:-P3D",
                "END:VALARM",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape_ical(f'URGENT: 1 day remaining to apply for {org} — {title}')}",
                "TRIGGER:-P1D",
                "END:VALARM",
                "END:VEVENT",
            ])

        # 2. Examination Date Event
        exam_date = parse_date(exam_date_str)
        if exam_date:
            e_start = exam_date.strftime("%Y%m%d")
            e_end = (exam_date + timedelta(days=1)).strftime("%Y%m%d")

            e_desc_parts = [
                f"Organisation: {org}",
                f"Post: {title}",
                f"Exam Category: {cat}",
                f"Exam Date: {exam_date_str}",
                f"Status: {status}",
            ]
            roll_num = getattr(job, "roll_number", "") or ""
            if roll_num:
                e_desc_parts.append(f"Roll / Admit Card: {roll_num}")
            if notes:
                e_desc_parts.append(f"Notes: {notes}")
            if url:
                e_desc_parts.append(f"Notice URL: {url}")

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:grt-job-{job_id}-exam@govrecruitmenttracker",
                f"DTSTAMP:{now_utc}",
                f"DTSTART;VALUE=DATE:{e_start}",
                f"DTEND;VALUE=DATE:{e_end}",
                f"SUMMARY:{_escape_ical(f'📝 Exam Date: {org} — {title}')}",
                f"DESCRIPTION:{_escape_ical(chr(10).join(e_desc_parts))}",
                f"CATEGORIES:{_escape_ical(str(cat))}",
                "STATUS:CONFIRMED",
            ])
            if url:
                lines.append(f"URL:{url}")

            lines.extend([
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape_ical(f'Exam in 7 days: {org} — {title}')}",
                "TRIGGER:-P7D",
                "END:VALARM",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape_ical(f'URGENT: Exam tomorrow: {org} — {title}')}",
                "TRIGGER:-P1D",
                "END:VALARM",
                "END:VEVENT",
            ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if "--setup" in sys.argv:
        sys.exit(0 if run_oauth_setup() else 1)
    print("Usage: python calendar_sync.py --setup")

