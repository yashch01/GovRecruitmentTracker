"""
tests/test_milestone4.py — Unit & Integration tests for Milestone 4:
  - calendar_sync.py (Google Calendar OAuth2, individual events, reminders, CRUD)
  - telegram_notifier.py (Telegram Bot API alerts, non-blocking async, formatting)
"""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import date
from unittest.mock import MagicMock, patch

# Ensure root directory is on Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import calendar_sync
import telegram_notifier

# ─── Terminal colours ────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

_pass = 0
_fail = 0


def _assert(condition: bool, label: str, detail: str = ""):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  {GREEN}✓ PASS{RESET}  {label}")
    else:
        _fail += 1
        print(f"  {RED}✗ FAIL{RESET}  {label}")
        if detail:
            print(f"         {YELLOW}→ {detail}{RESET}")


def section(title: str):
    print(f"\n{BOLD}{CYAN}{'─'*65}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*65}{RESET}")


# ─── Mock Job Helper ──────────────────────────────────────────────────────────
class MockJob:
    def __init__(
        self,
        id: int = 1,
        title: str = "Scientist / Engineer 'SC' (Computer Science)",
        organization: str = "ISRO / VSSC",
        exam_category: str = "Technical CS/IT",
        pay_level_or_ctc: str = "Level 10 (₹56,100 - ₹1,77,500)",
        educational_qualifications: str = "B.E/B.Tech in CS/IT with First Class 65%",
        gate_required: bool = False,
        age_limit_details: str = "Max 30 years as on 15/11/2024",
        selection_summary: str = "Written test followed by Interview (1:5 ratio)",
        last_date: str = "15/11/2024",
        exam_date: str = "22/12/2024",
        notification_url: str = "https://www.vssc.gov.in/advt324.html",
        pdf_url: str = "https://www.vssc.gov.in/advt324.pdf",
        eligible_cs_it: bool = True,
        is_synced_to_calendar: bool = False,
        calendar_event_id: str = "",
    ):
        self.id = id
        self.title = title
        self.organization = organization
        self.exam_category = exam_category
        self.pay_level_or_ctc = pay_level_or_ctc
        self.educational_qualifications = educational_qualifications
        self.gate_required = gate_required
        self.age_limit_details = age_limit_details
        self.selection_summary = selection_summary
        self.last_date = last_date
        self.exam_date = exam_date
        self.notification_url = notification_url
        self.pdf_url = pdf_url
        self.eligible_cs_it = eligible_cs_it
        self.is_synced_to_calendar = is_synced_to_calendar
        self.calendar_event_id = calendar_event_id


# ============================================================================
# Section 1: calendar_sync.py — Date Parsing
# ============================================================================
def test_calendar_date_parsing():
    section("1. calendar_sync.py — Indian & International Date Parsing")

    # Standard formats
    _assert(calendar_sync.parse_date("15/11/2024") == date(2024, 11, 15), "DD/MM/YYYY parsed correctly")
    _assert(calendar_sync.parse_date("15-11-2024") == date(2024, 11, 15), "DD-MM-YYYY parsed correctly")
    _assert(calendar_sync.parse_date("2024-11-15") == date(2024, 11, 15), "YYYY-MM-DD parsed correctly")
    _assert(calendar_sync.parse_date("15 November 2024") == date(2024, 11, 15), "DD Month YYYY parsed correctly")
    _assert(calendar_sync.parse_date("15 Nov 2024") == date(2024, 11, 15), "DD Mon YYYY parsed correctly")
    _assert(calendar_sync.parse_date("November 15, 2024") == date(2024, 11, 15), "Month DD, YYYY parsed correctly")

    # Ordinal dates (1st, 2nd, 3rd, 4th...)
    _assert(calendar_sync.parse_date("1st December 2024") == date(2024, 12, 1), "1st December 2024 ordinal parsed")
    _assert(calendar_sync.parse_date("2nd January 2025") == date(2025, 1, 2), "2nd January 2025 ordinal parsed")
    _assert(calendar_sync.parse_date("3rd March 2025") == date(2025, 3, 3), "3rd March 2025 ordinal parsed")
    _assert(calendar_sync.parse_date("31st October 2024") == date(2024, 10, 31), "31st October 2024 ordinal parsed")

    # Embedded dates in sentences
    _assert(
        calendar_sync.parse_date("Last date for submission is 2025-05-30 up to 5:00 PM") == date(2025, 5, 30),
        "Embedded ISO date in sentence extracted",
    )

    # Empty and invalid cases
    _assert(calendar_sync.parse_date("") is None, "Empty string returns None")
    _assert(calendar_sync.parse_date("   ") is None, "Whitespace string returns None")
    _assert(calendar_sync.parse_date(None) is None, "None input returns None")  # type: ignore
    _assert(calendar_sync.parse_date("Not specified / To be announced") is None, "Non-date text returns None")


# ============================================================================
# Section 2: calendar_sync.py — Event Payload Construction
# ============================================================================
def test_calendar_event_body():
    section("2. calendar_sync.py — Event Body & Reminders Construction")

    job = MockJob(id=42, organization="NIC", title="Scientist B", exam_category="Technical CS/IT", eligible_cs_it=True)
    body = calendar_sync.build_event_body(job, date(2024, 11, 15), "deadline")

    # Title & Emojis
    _assert("🚨 LAST DATE:" in body["summary"], "Deadline title contains 🚨 LAST DATE:")
    _assert("NIC" in body["summary"], "Summary contains organization name")
    _assert("(CS/IT)" in body["summary"], "Summary contains (CS/IT) tag for CS/IT post")

    # Exam event
    exam_body = calendar_sync.build_event_body(job, date(2024, 12, 22), "exam")
    _assert("📝 EXAM:" in exam_body["summary"], "Exam title contains 📝 EXAM:")

    # Dates
    _assert(body["start"]["date"] == "2024-11-15", "Event start is all-day date string")
    _assert(body["end"]["date"] == "2024-11-16", "Event end is next day for all-day duration")

    # Color Mapping by Category
    _assert(body["colorId"] == "2", "Technical CS/IT mapped to colorId '2' (Sage)")

    psu_job = MockJob(exam_category="PSU")
    _assert(calendar_sync.build_event_body(psu_job, date(2024, 11, 15))["colorId"] == "5", "PSU mapped to colorId '5'")

    comp_job = MockJob(exam_category="Competitive Exam")
    _assert(calendar_sync.build_event_body(comp_job, date(2024, 11, 15))["colorId"] == "7", "Competitive Exam mapped to colorId '7'")

    bank_job = MockJob(exam_category="Banking")
    _assert(calendar_sync.build_event_body(bank_job, date(2024, 11, 15))["colorId"] == "9", "Banking mapped to colorId '9'")

    mil_job = MockJob(exam_category="Military")
    _assert(calendar_sync.build_event_body(mil_job, date(2024, 11, 15))["colorId"] == "11", "Military mapped to colorId '11'")

    # Reminders: must include 7d, 3d, 1d popups
    reminders = body["reminders"]
    _assert(reminders["useDefault"] is False, "Default calendar reminders disabled")
    overrides = reminders["overrides"]
    minutes_list = [ov["minutes"] for ov in overrides]
    _assert(7 * 24 * 60 in minutes_list, "7-day popup reminder present (10080 min)")
    _assert(3 * 24 * 60 in minutes_list, "3-day popup reminder present (4320 min)")
    _assert(1 * 24 * 60 in minutes_list, "1-day popup reminder present (1440 min)")
    _assert(len(overrides) == 3, "Exactly 3 popup reminders configured")

    # Extended properties (idempotency key)
    private_props = body["extendedProperties"]["private"]
    _assert(private_props["grt_job_id"] == "42", "grt_job_id matches job.id")
    _assert(private_props["grt_event_type"] == "deadline", "grt_event_type matches 'deadline'")
    _assert(private_props["grt_organization"] == "NIC", "grt_organization matches 'NIC'")

    # Long title truncation
    long_job = MockJob(organization="A" * 60, title="B" * 60)
    long_body = calendar_sync.build_event_body(long_job, date(2024, 11, 15))
    _assert(len(long_body["summary"]) <= 100, "Titles over 100 chars truncated to <= 100 chars")
    _assert(long_body["summary"].endswith("…"), "Truncated title ends with ellipsis")


# ============================================================================
# Section 3: calendar_sync.py — Calendar Service Operations (Mocked)
# ============================================================================
def test_calendar_service_ops():
    section("3. calendar_sync.py — CRUD Operations & Idempotent Upsert")

    # Build a mock Google Calendar service
    mock_service = MagicMock()
    events_resource = MagicMock()
    mock_service.events.return_value = events_resource

    # Test 3.1: _find_existing_event when event exists
    events_resource.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "existing_ev_123",
                "extendedProperties": {
                    "private": {
                        "grt_job_id": "101",
                        "grt_event_type": "deadline",
                    }
                },
            }
        ]
    }
    found_id = calendar_sync._find_existing_event(mock_service, 101, "deadline")
    _assert(found_id == "existing_ev_123", "Found existing event returns correct ID")

    # Test 3.2: _find_existing_event when not found
    events_resource.list.return_value.execute.return_value = {"items": []}
    not_found_id = calendar_sync._find_existing_event(mock_service, 999, "deadline")
    _assert(not_found_id is None, "Missing event returns None")

    # Test 3.3: _upsert_event creates NEW event when none exists
    events_resource.list.return_value.execute.return_value = {"items": []}
    events_resource.insert.return_value.execute.return_value = {"id": "new_created_ev_456"}

    job = MockJob(id=101, last_date="15/11/2024", exam_date="20/12/2024")
    created_id = calendar_sync._upsert_event(mock_service, job, date(2024, 11, 15), "deadline")
    _assert(created_id == "new_created_ev_456", "New event created successfully and returns event ID")
    _assert(events_resource.insert.called, "events().insert() was called")

    # Test 3.4: _upsert_event UPDATES event when already exists
    events_resource.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "existing_ev_123",
                "extendedProperties": {"private": {"grt_job_id": "101", "grt_event_type": "deadline"}},
            }
        ]
    }
    events_resource.update.return_value.execute.return_value = {"id": "existing_ev_123"}
    updated_id = calendar_sync._upsert_event(mock_service, job, date(2024, 11, 15), "deadline")
    _assert(updated_id == "existing_ev_123", "Existing event updated in-place (idempotent)")
    _assert(events_resource.update.called, "events().update() was called instead of insert")

    # Test 3.5: sync_job_to_calendar creates both deadline and exam events and updates job ORM attrs
    events_resource.list.return_value.execute.return_value = {"items": []}
    events_resource.insert.return_value.execute.side_effect = [
        {"id": "ev_deadline_1"},
        {"id": "ev_exam_1"},
    ]
    res = calendar_sync.sync_job_to_calendar(job, service=mock_service)
    _assert(res["deadline_event_id"] == "ev_deadline_1", "Deadline event synced")
    _assert(res["exam_event_id"] == "ev_exam_1", "Exam event synced")
    _assert(res["error"] is None, "No error reported on successful sync")
    _assert(job.is_synced_to_calendar is True, "job.is_synced_to_calendar set to True")
    _assert(job.calendar_event_id in ("ev_deadline_1", "ev_exam_1"), "job.calendar_event_id populated")

    # Test 3.6: sync_job_to_calendar handles unavailable service gracefully
    job_unavail = MockJob(id=202)
    with patch("calendar_sync._build_service", return_value=None):
        res_unavail = calendar_sync.sync_job_to_calendar(job_unavail, service=None)
        _assert(res_unavail["deadline_event_id"] is None, "Deadline event None when service unavailable")
        _assert("unavailable" in res_unavail["error"].lower(), "Returns graceful error message")

    # Test 3.7: delete_job_events
    events_resource.list.return_value.execute.side_effect = [
        {"items": [{"id": "ev_deadline_del", "extendedProperties": {"private": {"grt_job_id": "101", "grt_event_type": "deadline"}}}]},
        {"items": [{"id": "ev_exam_del", "extendedProperties": {"private": {"grt_job_id": "101", "grt_event_type": "exam"}}}]},
    ]
    events_resource.delete.return_value.execute.return_value = None
    deleted_count = calendar_sync.delete_job_events(101, service=mock_service)
    _assert(deleted_count == 2, "delete_job_events deleted both deadline and exam events (count = 2)")

    # Test 3.8: sync_all_jobs bulk sync
    jobs_list = [
        MockJob(id=1, last_date="15/11/2024"),
        MockJob(id=2, last_date="20/11/2024"),
        MockJob(id=3, last_date="", exam_date=""),  # no dates -> skipped
    ]
    events_resource.list.return_value.execute.side_effect = None
    events_resource.list.return_value.execute.return_value = {"items": []}
    events_resource.insert.return_value.execute.side_effect = None
    events_resource.insert.return_value.execute.return_value = {"id": "bulk_ev"}
    bulk_summary = calendar_sync.sync_all_jobs(jobs_list, service=mock_service)
    _assert(bulk_summary["synced"] == 2, "Bulk sync correctly synced 2 jobs with dates")
    _assert(bulk_summary["skipped"] == 1, "Bulk sync skipped 1 job without dates")
    _assert(bulk_summary["errors"] == 0, "Bulk sync had 0 errors")


# ============================================================================
# Section 4: telegram_notifier.py — Credentials Resolution
# ============================================================================
def test_telegram_credentials():
    section("4. telegram_notifier.py — Credentials Resolution & Config Checks")

    # Test 4.1: Explicit credentials
    tok, chat = telegram_notifier.get_telegram_credentials("bot123", "chat456")
    _assert(tok == "bot123" and chat == "chat456", "Explicit credentials returned directly")
    _assert(telegram_notifier.is_telegram_configured("bot123", "chat456") is True, "is_telegram_configured True with args")

    # Test 4.2: Unconfigured credentials
    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}, clear=True):
        tok_empty, chat_empty = telegram_notifier.get_telegram_credentials("", "")
        _assert(tok_empty == "" and chat_empty == "", "Returns empty strings when unconfigured")
        _assert(telegram_notifier.is_telegram_configured("", "") is False, "is_telegram_configured False when empty")

    # Test 4.3: Environment variables fallback
    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "env_token_abc", "TELEGRAM_CHAT_ID": "-100123456"}):
        tok_env, chat_env = telegram_notifier.get_telegram_credentials()
        _assert(tok_env == "env_token_abc", "Bot token resolved from TELEGRAM_BOT_TOKEN env var")
        _assert(chat_env == "-100123456", "Chat ID resolved from TELEGRAM_CHAT_ID env var")
        _assert(telegram_notifier.is_telegram_configured() is True, "is_telegram_configured True via env vars")


# ============================================================================
# Section 5: telegram_notifier.py — HTML Message Formatting
# ============================================================================
def test_telegram_message_formatting():
    section("5. telegram_notifier.py — HTML Message Formatting & Safety")

    # Test 5.1: Rich job details in HTML
    job = MockJob(
        id=7,
        title="Senior Technical Officer (CS)",
        organization="CDAC & NIELIT",
        exam_category="Technical CS/IT",
        pay_level_or_ctc="₹80,000/month consolidated",
        educational_qualifications="B.Tech CS / MCA with 60%",
        gate_required=False,
        age_limit_details="35 years",
        selection_summary="Interview only",
        last_date="10/12/2024",
        exam_date="20/01/2025",
        notification_url="https://example.com/notice?id=12&ref=gov",
        pdf_url="https://example.com/notice.pdf",
    )

    msg = telegram_notifier.format_job_message(job)

    _assert("🚨 <b>NEW GOVT RECRUITMENT ALERT</b>" in msg, "Header banner present")
    _assert("🏢 <b>Organisation:</b> CDAC &amp; NIELIT" in msg, "Organization escaped with &amp;")
    _assert("💼 <b>Post / Exam:</b> Senior Technical Officer (CS)" in msg, "Post title present")
    _assert("💻 <b>Category:</b> Technical CS/IT" in msg, "Technical CS/IT has laptop emoji")
    _assert("✅ <b>No (Direct / Written Exam)</b>" in msg, "GATE not required badge rendered")
    _assert("💰 <b>Pay / Scale:</b> ₹80,000/month consolidated" in msg, "Pay scale included")
    _assert("⏳ <b>Last Date:</b> 10/12/2024" in msg, "Last date included")
    _assert("📝 <b>Exam Date:</b> 20/01/2025" in msg, "Exam date included")
    _assert('<a href="https://example.com/notice?id=12&amp;ref=gov">🌐 Official Portal</a>' in msg, "Notice link safely formatted")
    _assert('<a href="https://example.com/notice.pdf">📄 Download PDF</a>' in msg, "PDF link safely formatted")
    _assert("Tracked by GovRecruitmentTracker (ID #7)" in msg, "Footer with job ID present")

    # Test 5.2: GATE Required badge
    gate_job = MockJob(gate_required=True)
    gate_msg = telegram_notifier.format_job_message(gate_job)
    _assert("⚠️ <b>Yes (GATE Score Required)</b>" in gate_msg, "GATE Required badge rendered")

    # Test 5.3: HTML Injection Safety
    malicious_job = MockJob(
        organization="<script>alert('xss')</script>",
        title="Post <bold> & 'Quotes' & \"Double\"",
    )
    safe_msg = telegram_notifier.format_job_message(malicious_job)
    _assert("<script>" not in safe_msg, "Raw <script> tag not in message")
    _assert("&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in safe_msg or "&lt;script&gt;" in safe_msg, "HTML tags safely escaped")
    _assert("&amp;" in safe_msg, "Ampersands safely escaped")


# ============================================================================
# Section 6: telegram_notifier.py — Synchronous Sending & Error Handling
# ============================================================================
def test_telegram_sync_sending():
    section("6. telegram_notifier.py — Synchronous Sending & Resilience")

    # Test 6.1: Missing credentials skips silently
    result_skip = telegram_notifier.send_message("Test text", chat_id="", bot_token="")
    _assert(result_skip is False, "send_message returns False silently when credentials empty")

    # Test 6.2: Successful send (HTTP 200)
    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {"ok": True}

    with patch("requests.post", return_value=mock_resp_200) as mock_post:
        success = telegram_notifier.send_message(
            "Hello World",
            chat_id="12345",
            bot_token="token_xyz",
        )
        _assert(success is True, "send_message returns True on HTTP 200")
        _assert(mock_post.called, "requests.post was called")
        call_kwargs = mock_post.call_args[1]
        _assert(call_kwargs["json"]["chat_id"] == "12345", "Payload contains correct chat_id")
        _assert(call_kwargs["json"]["text"] == "Hello World", "Payload contains message text")
        _assert(call_kwargs["json"]["parse_mode"] == "HTML", "Payload parse_mode is HTML")

    # Test 6.3: API Error (HTTP 400)
    mock_resp_400 = MagicMock()
    mock_resp_400.status_code = 400
    mock_resp_400.text = "Bad Request: chat not found"

    with patch("requests.post", return_value=mock_resp_400):
        failed_res = telegram_notifier.send_message("Hello", chat_id="bad_chat", bot_token="token_xyz")
        _assert(failed_res is False, "send_message returns False on HTTP 400 without throwing exception")

    # Test 6.4: Network Connection Exception
    with patch("requests.post", side_effect=Exception("Connection timed out")):
        exc_res = telegram_notifier.send_message("Hello", chat_id="12345", bot_token="token_xyz")
        _assert(exc_res is False, "send_message returns False on network timeout/exception without crashing")

    # Test 6.5: send_test_message
    with patch("requests.post", return_value=mock_resp_200):
        ok, msg = telegram_notifier.send_test_message(chat_id="12345", bot_token="token_xyz")
        _assert(ok is True, "send_test_message returns True on success")
        _assert("successfully" in msg.lower(), "Success message returned")

    with patch("requests.post", return_value=mock_resp_400):
        mock_resp_400.json.return_value = {"description": "Unauthorized"}
        ok, msg = telegram_notifier.send_test_message(chat_id="12345", bot_token="bad_token")
        _assert(ok is False, "send_test_message returns False on error")
        _assert("Unauthorized" in msg or "400" in msg, "Error description included in return")

    ok_unconf, msg_unconf = telegram_notifier.send_test_message(chat_id="", bot_token="")
    _assert(ok_unconf is False, "send_test_message returns False when unconfigured")


# ============================================================================
# Section 7: telegram_notifier.py — Non-Blocking Async Dispatch
# ============================================================================
def test_telegram_async_dispatch():
    section("7. telegram_notifier.py — Non-blocking Async Dispatch & Batching")

    # Test 7.1: send_message_async returns started Thread immediately
    mock_resp = MagicMock(status_code=200)
    with patch("requests.post", return_value=mock_resp):
        t0 = time.time()
        thread = telegram_notifier.send_message_async(
            "Async Test Message",
            chat_id="12345",
            bot_token="tok",
        )
        elapsed = time.time() - t0

        _assert(isinstance(thread, threading.Thread), "send_message_async returns a threading.Thread instance")
        _assert(elapsed < 0.1, f"send_message_async returned immediately in {elapsed*1000:.1f}ms (<100ms)")
        thread.join(timeout=2.0)
        _assert(not thread.is_alive(), "Background worker thread completed cleanly")

    # Test 7.2: notify_new_job in async mode
    job = MockJob(id=99)
    with patch("requests.post", return_value=mock_resp):
        res_thread = telegram_notifier.notify_new_job(
            job,
            chat_id="12345",
            bot_token="tok",
            async_send=True,
        )
        _assert(isinstance(res_thread, threading.Thread), "notify_new_job(async_send=True) returns Thread")
        if isinstance(res_thread, threading.Thread):
            res_thread.join(timeout=2.0)

    # Test 7.3: notify_new_job in sync mode
    with patch("requests.post", return_value=mock_resp):
        sync_res = telegram_notifier.notify_new_job(
            job,
            chat_id="12345",
            bot_token="tok",
            async_send=False,
        )
        _assert(sync_res is True, "notify_new_job(async_send=False) returns bool True")

    # Test 7.4: notify_new_job skips when unconfigured
    skip_res = telegram_notifier.notify_new_job(job, chat_id="", bot_token="", async_send=False)
    _assert(skip_res is False, "notify_new_job returns False when unconfigured")

    # Test 7.5: notify_jobs_batch in sync mode
    batch_jobs = [MockJob(id=1), MockJob(id=2), MockJob(id=3)]
    with patch("requests.post", return_value=mock_resp):
        delivered = telegram_notifier.notify_jobs_batch(
            batch_jobs,
            chat_id="12345",
            bot_token="tok",
            async_send=False,
            interval_sec=0.01,
        )
        _assert(delivered == 3, f"notify_jobs_batch delivered all 3 jobs (count = {delivered})")

    # Test 7.6: notify_jobs_batch in async mode
    with patch("requests.post", return_value=mock_resp):
        batch_thread = telegram_notifier.notify_jobs_batch(
            batch_jobs,
            chat_id="12345",
            bot_token="tok",
            async_send=True,
            interval_sec=0.01,
        )
        _assert(isinstance(batch_thread, threading.Thread), "notify_jobs_batch(async_send=True) returns Thread")
        if isinstance(batch_thread, threading.Thread):
            batch_thread.join(timeout=2.0)
            _assert(not batch_thread.is_alive(), "Batch async thread completed cleanly")


# ============================================================================
# Main Test Runner
# ============================================================================
def main():
    print(f"\n{BOLD}{GREEN}================================================================={RESET}")
    print(f"{BOLD}{GREEN}  GovRecruitmentTracker — Milestone 4 Test Suite                 {RESET}")
    print(f"{BOLD}{GREEN}  (Google Calendar Sync + Telegram Non-blocking Notifier)        {RESET}")
    print(f"{BOLD}{GREEN}================================================================={RESET}")

    test_calendar_date_parsing()
    test_calendar_event_body()
    test_calendar_service_ops()
    test_telegram_credentials()
    test_telegram_message_formatting()
    test_telegram_sync_sending()
    test_telegram_async_dispatch()

    print(f"\n{BOLD}{CYAN}{'═'*65}{RESET}")
    print(f"{BOLD}  Milestone 4 Test Results:{RESET}")
    print(f"  Passed: {GREEN}{_pass}{RESET}")
    print(f"  Failed: {RED}{_fail}{RESET}")
    print(f"{BOLD}{CYAN}{'═'*65}{RESET}\n")

    if _fail > 0:
        print(f"{RED}{BOLD}Some tests failed!{RESET}")
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}✓ All Milestone 4 tests passed successfully!{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
