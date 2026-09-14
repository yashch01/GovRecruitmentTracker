"""
tests/test_milestone8.py — Milestone 8 Automated Tests for Cloud Cron Sync & Admit Card Auto-Detector.

Validates:
  1. Cron Token Security & Authentication (Query Param, X-Cron-Token, Bearer Header, 401 Rejection)
  2. Admit Card & Hall Ticket Keyword Detector Engine (scan_for_admit_card)
  3. Automated Status Promotion to 'Admit Card Out' for Applied Jobs
  4. Auto-Notes Appending & Telegram Alert Dispatch on Release
  5. Full /api/cron/sync Integration Response Structure
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from blueprints.api import (
    ADMIT_CARD_KEYWORDS,
    check_applied_jobs_admit_cards,
    scan_for_admit_card,
)
from models import ExamCategory, Job, UserStatus, db

# ─── Colours for test runner ────────────────────────────────────────────────
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


def setup_test_app(cron_token: str = "test-secret-cron-token-123"):
    """Create test Flask app configured with in-memory SQLite and custom cron token."""
    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SECRET_KEY": "test-secret-key",
        "CRON_TOKEN": cron_token,
        "ARCHIVES_DIR": "/tmp/grt_test_archives",
    }
    app = create_app(test_config)
    with app.app_context():
        db.create_all()
    return app


def run_tests():
    print(f"\n{BOLD}================================================================={RESET}")
    print(f"{BOLD}  Milestone 8: Cloud Cron Trigger & Admit Card Auto-Detector Tests{RESET}")
    print(f"{BOLD}================================================================={RESET}")

    # ─── 1. Admit Card Keyword Detection Engine ─────────────────────────────────
    section("1. Admit Card Keyword Detection Engine")

    _assert("admit card" in ADMIT_CARD_KEYWORDS, "ADMIT_CARD_KEYWORDS contains 'admit card'")
    _assert("hall ticket" in ADMIT_CARD_KEYWORDS, "ADMIT_CARD_KEYWORDS contains 'hall ticket'")
    _assert("call letter" in ADMIT_CARD_KEYWORDS, "ADMIT_CARD_KEYWORDS contains 'call letter'")
    _assert("city intimation" in ADMIT_CARD_KEYWORDS, "ADMIT_CARD_KEYWORDS contains 'city intimation'")

    # Mock session with Admit Card release HTML
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body><h1>Notice: Download e-Admit Card for Scientist B CBT Exam</h1></body></html>"
    mock_session.get.return_value = mock_resp

    found, kw = scan_for_admit_card("https://nic.gov.in/careers", session=mock_session)
    _assert(found is True, "scan_for_admit_card detects 'admit card' in HTML text")
    _assert("admit" in kw, f"Detected keyword matches: {kw}")

    # Test negative detection (no keywords)
    mock_resp_neg = MagicMock()
    mock_resp_neg.status_code = 200
    mock_resp_neg.text = "<html><body><h1>General Syllabus and Application Guidelines</h1></body></html>"
    mock_session.get.return_value = mock_resp_neg

    found_neg, kw_neg = scan_for_admit_card("https://nic.gov.in/careers", session=mock_session)
    _assert(found_neg is False, "scan_for_admit_card returns False when keywords are absent")
    _assert(kw_neg == "", "Matched keyword is empty string on negative detection")

    # Test invalid / empty URL handling
    f_empty, _ = scan_for_admit_card("", session=mock_session)
    _assert(f_empty is False, "Empty URL handled safely without error")
    f_nonhttp, _ = scan_for_admit_card("ftp://invalid-protocol", session=mock_session)
    _assert(f_nonhttp is False, "Non-HTTP URL handled safely without error")

    # ─── 2. Cron Authentication Security ─────────────────────────────────────────
    section("2. Cron Authentication Security")

    app = setup_test_app(cron_token="super-secret-cron-token")
    client = app.test_client()

    # 2a. Request without token → HTTP 401 Unauthorized
    res_no_token = client.get("/api/cron/sync")
    _assert(res_no_token.status_code == 401, "GET /api/cron/sync without token returns HTTP 401")
    _assert("Unauthorized" in res_no_token.get_json().get("message", ""), "401 response specifies Unauthorized")

    # 2b. Request with wrong token → HTTP 401 Unauthorized
    res_bad_token = client.get("/api/cron/sync?token=wrong-token-abc")
    _assert(res_bad_token.status_code == 401, "GET /api/cron/sync with incorrect token returns HTTP 401")

    # 2c. Request with correct token in query param → HTTP 200 OK
    res_query_token = client.get("/api/cron/sync?token=super-secret-cron-token")
    _assert(res_query_token.status_code == 200, "GET /api/cron/sync?token=... returns HTTP 200 OK")
    _assert(res_query_token.get_json().get("status") == "success", "Response reports status == 'success'")
    _assert(res_query_token.get_json().get("scrapers_dispatched") is True, "Response confirms scrapers_dispatched == True")

    # 2d. Request with X-Cron-Token header → HTTP 200 OK
    res_header_token = client.get("/api/cron/sync", headers={"X-Cron-Token": "super-secret-cron-token"})
    _assert(res_header_token.status_code == 200, "GET /api/cron/sync with X-Cron-Token header returns HTTP 200 OK")

    # 2e. Request with Authorization: Bearer token → HTTP 200 OK
    res_bearer_token = client.post("/api/cron/sync", headers={"Authorization": "Bearer super-secret-cron-token"})
    _assert(res_bearer_token.status_code == 200, "POST /api/cron/sync with Bearer header returns HTTP 200 OK")

    # ─── 3. Automated Status Promotion & Telegram Alert ──────────────────────────
    section("3. Automated Status Promotion & Telegram Alert")

    with app.app_context():
        # Seed test jobs: 1 Applied (will detect admit card), 1 Not Applied (should be untouched)
        j_applied = Job(
            title="Scientist B (CS)",
            organization="NIC",
            exam_category=ExamCategory.TECHNICAL_CS_IT,
            gate_required=False,
            last_date="15/12/2026",
            user_status=UserStatus.APPLIED,
            registration_number="NIC-REG-9912",
            notification_url="https://recruitment.nic.in/scientist-b",
            notes="Initial personal notes.",
        )
        j_not_applied = Job(
            title="Executive Trainee (IT)",
            organization="IOCL",
            exam_category=ExamCategory.PSU,
            gate_required=True,
            last_date="01/10/2026",
            user_status=UserStatus.NOT_APPLIED,
            notification_url="https://iocl.com/jobs",
        )
        db.session.add_all([j_applied, j_not_applied])
        db.session.commit()

        # Mock portal response indicating admit card release
        mock_portal_resp = MagicMock()
        mock_portal_resp.status_code = 200
        mock_portal_resp.text = "<html><body><h2>Admit Card Download Link for NIC Scientist B Online CBT</h2></body></html>"

        with patch("requests.Session.get", return_value=mock_portal_resp):
            with patch("telegram_notifier.send_message_async") as mock_tg:
                detected = check_applied_jobs_admit_cards()

                _assert(len(detected) == 1, f"Detected 1 admit card release (got {len(detected)})")
                _assert(detected[0]["organization"] == "NIC", "Detected job is NIC")
                _assert("admit card" in detected[0]["keyword"], f"Matched keyword: {detected[0]['keyword']}")

                # Verify Job in DB was promoted to ADMIT_CARD_OUT
                refreshed_job = db.session.get(Job, j_applied.id)
                _assert(refreshed_job is not None and refreshed_job.application_status == UserStatus.ADMIT_CARD_OUT, "Job application_status promoted to ADMIT_CARD_OUT")
                _assert(refreshed_job is not None and "[Auto-Detected]" in refreshed_job.notes, "Job notes contains [Auto-Detected] timestamp log")
                _assert(refreshed_job is not None and "NIC-REG-9912" in refreshed_job.registration_number, "Registration number preserved")

                # Verify Not Applied job was untouched
                unapplied_job = db.session.get(Job, j_not_applied.id)
                _assert(unapplied_job is not None and unapplied_job.application_status == UserStatus.NOT_APPLIED, "Not Applied job remained untouched")

                # Verify Telegram alert was dispatched
                _assert(mock_tg.called, "send_message_async was called to dispatch urgent Telegram alert")
                alert_text = mock_tg.call_args[0][0]
                _assert("Admit Card / Hall Ticket Alert!" in alert_text, "Telegram alert contains alert banner")
                _assert("NIC-REG-9912" in alert_text, "Telegram alert includes user's Registration ID")

    # ─── 4. End-to-End Cron Trigger Integration ──────────────────────────────────
    section("4. End-to-End Cron Trigger Integration")

    with patch("blueprints.jobs._run_fetch_in_background") as mock_fetch:
        with patch("blueprints.api.check_applied_jobs_admit_cards") as mock_check:
            mock_check.return_value = [{"job_id": 1, "organization": "NIC", "keyword": "admit card"}]

            res = client.get("/api/cron/sync?token=super-secret-cron-token")
            _assert(res.status_code == 200, "Cron trigger returns HTTP 200 OK")
            _assert(mock_fetch.called, "Background scraper fetch was dispatched")
            json_body = res.get_json()
            _assert(json_body.get("scrapers_dispatched") is True, "Background scrapers dispatched")
            _assert(json_body.get("newly_detected_count") == 1, "newly_detected_count reports 1")
            _assert(len(json_body.get("admit_cards_detected", [])) == 1, "admit_cards_detected list populated")

    # ─── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}═════════════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Milestone 8 Test Results:{RESET}")
    print(f"  {GREEN}Passed: {_pass}{RESET}")
    print(f"  {RED if _fail else GREEN}Failed: {_fail}{RESET}")
    print(f"{BOLD}═════════════════════════════════════════════════════════════════{RESET}")

    if _fail > 0:
        print(f"\n{RED}✗ Some tests failed!{RESET}\n")
        sys.exit(1)
    else:
        print(f"\n{GREEN}✓ All Milestone 8 tests passed successfully!{RESET}\n")


if __name__ == "__main__":
    run_tests()
