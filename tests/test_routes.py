"""
tests/test_routes.py — Comprehensive Route & Blueprint Integration Tests for Milestone 5.

Covers:
  1. Application Factory & Blueprint Registration (6 blueprints)
  2. Dashboard Blueprint (HTML rendering, JSON mode, KPI metrics, filters)
  3. Jobs Blueprint (status tracking, notes, non-blocking /fetch-now, calendar sync, delete)
  4. Sources Blueprint (list, add portal, validation, duplicate prevention, toggle, delete)
  5. Settings Blueprint (view, update DOB/category/tokens/flags, test-telegram)
  6. Auth Blueprint (OAuth redirect, status check, disconnect)
  7. API Blueprint (health, metrics, jobs listing, pagination, update status, sources, fetch-now)
  8. Error Handlers (404 JSON for API, HTML for web)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from unittest.mock import patch

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from models import ExamCategory, Job, ReservationCategory, Source, UserSettings, UserStatus, db

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


def setup_test_app():
    """Create a test Flask app configured with in-memory SQLite."""
    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SECRET_KEY": "test-key-for-testing",
        "ARCHIVES_DIR": "/tmp/grt_test_archives",
        "WTF_CSRF_ENABLED": False,
    }
    app = create_app(test_config)

    with app.app_context():
        db.create_all()

        # Seed test sources
        s1 = Source(name="NIELIT", url="https://nielit.gov.in/recruitments", category=ExamCategory.TECHNICAL_CS_IT, scraper_type="NIELITScraper", is_active=True)
        s2 = Source(name="UPSC", url="https://upsc.gov.in/examinations", category=ExamCategory.COMPETITIVE_EXAM, scraper_type="UPSCScraper", is_active=True)
        s3 = Source(name="Inactive Portal", url="https://inactive.gov.in", category=ExamCategory.OTHER, scraper_type="GenericCareerScraper", is_active=False)
        db.session.add_all([s1, s2, s3])

        # Seed test jobs
        j1 = Job(
            title="Scientist B (CS)",
            organization="NIC",
            exam_category=ExamCategory.TECHNICAL_CS_IT,
            gate_required=False,
            eligible_cs_it=True,
            last_date="15/12/2026",
            exam_date="20/01/2027",
            user_status=UserStatus.NOT_APPLIED,
            notification_url="https://nic.gov.in/job1",
            is_synced_to_calendar=False,
        )
        j2 = Job(
            title="Executive Trainee (IT)",
            organization="IOCL",
            exam_category=ExamCategory.PSU,
            gate_required=True,
            eligible_cs_it=True,
            last_date="01/10/2026",
            exam_date="",
            user_status=UserStatus.APPLIED,
            notification_url="https://iocl.com/job2",
            is_synced_to_calendar=True,
        )
        j3 = Job(
            title="Combined Graduate Level (CGL)",
            organization="SSC",
            exam_category=ExamCategory.COMPETITIVE_EXAM,
            gate_required=False,
            eligible_cs_it=True,
            last_date="01/01/2025",  # expired relative to future dates
            exam_date="",
            user_status=UserStatus.NOT_APPLIED,
            notification_url="https://ssc.nic.in/cgl",
            is_synced_to_calendar=False,
        )
        db.session.add_all([j1, j2, j3])

        # Seed user settings
        settings = UserSettings(
            date_of_birth=date(1998, 5, 20),
            category=ReservationCategory.OBC,
            telegram_bot_token="test_tok_123",
            telegram_chat_id="test_chat_456",
            feature_flags=json.dumps({"telegram_instant_alert": True}),
        )
        db.session.add(settings)
        db.session.commit()

    return app


# ============================================================================
# Section 1: Application Factory & Blueprint Registration
# ============================================================================
def test_app_factory():
    section("1. Application Factory & Blueprint Registration")
    app = setup_test_app()

    _assert(app is not None, "create_app() successfully instantiates Flask app")
    _assert(app.config["TESTING"] is True, "App configured with TESTING=True")
    _assert(os.path.exists("/tmp/grt_test_archives"), "Archives directory created automatically")

    # Verify all 6 blueprints registered
    registered = app.blueprints.keys()
    _assert("dashboard" in registered, "dashboard blueprint registered")
    _assert("jobs" in registered, "jobs blueprint registered")
    _assert("sources" in registered, "sources blueprint registered")
    _assert("settings" in registered, "settings blueprint registered")
    _assert("auth" in registered, "auth blueprint registered")
    _assert("api" in registered, "api blueprint registered")


# ============================================================================
# Section 2: Dashboard Blueprint
# ============================================================================
def test_dashboard_blueprint():
    section("2. Dashboard Blueprint (HTML, JSON, Metrics, Filters)")
    app = setup_test_app()
    client = app.test_client()

    # 2.1: GET / (HTML rendering)
    res_html = client.get("/")
    _assert(res_html.status_code == 200, "GET / returns HTTP 200 OK")
    _assert(b"GovRecruitmentTracker" in res_html.data, "HTML contains application branding")
    _assert(b"Scientist B (CS)" in res_html.data, "HTML renders seeded job title")
    _assert(b"IOCL" in res_html.data, "HTML renders seeded job organization")

    # 2.2: GET / (JSON mode via header)
    res_json = client.get("/", headers={"Accept": "application/json"})
    _assert(res_json.status_code == 200, "GET / with JSON Accept header returns 200")
    data = res_json.get_json()
    _assert("metrics" in data, "JSON response contains metrics")
    _assert("jobs" in data, "JSON response contains jobs list")
    _assert(data["metrics"]["total_jobs"] == 3, "Metrics report correct total jobs (3)")
    _assert(data["metrics"]["non_gate_cs_it"] == 1, "Metrics report correct Non-GATE CS/IT count (1)")
    _assert(data["metrics"]["applied_count"] == 1, "Metrics report correct Applied count (1)")
    _assert(data["metrics"]["synced_count"] == 1, "Metrics report correct Calendar Synced count (1)")

    # 2.3: Category filter
    res_cat = client.get("/?category=Technical+CS%2FIT", headers={"Accept": "application/json"})
    cat_data = res_cat.get_json()
    _assert(cat_data["jobs_count"] == 1, "Category filter returned only Technical CS/IT (1 job)")
    _assert(cat_data["jobs"][0]["organization"] == "NIC", "Correct job returned for Technical CS/IT")

    # 2.4: GATE filter
    res_gate = client.get("/?gate=gate_only", headers={"Accept": "application/json"})
    gate_data = res_gate.get_json()
    _assert(gate_data["jobs_count"] == 1, "GATE filter returned only GATE Required jobs (1 job)")
    _assert(gate_data["jobs"][0]["organization"] == "IOCL", "Correct GATE job returned")

    # 2.5: Search query
    res_search = client.get("/?search=Graduate", headers={"Accept": "application/json"})
    search_data = res_search.get_json()
    _assert(search_data["jobs_count"] == 1, "Search query matched 1 job")
    _assert(search_data["jobs"][0]["organization"] == "SSC", "Search correctly matched SSC CGL")


# ============================================================================
# Section 3: Jobs Blueprint
# ============================================================================
def test_jobs_blueprint():
    section("3. Jobs Blueprint (Status, Notes, Non-blocking Fetch, Sync)")
    app = setup_test_app()
    client = app.test_client()

    # 3.1: GET /jobs/<id>
    res_get = client.get("/jobs/1")
    _assert(res_get.status_code == 200, "GET /jobs/1 returns HTTP 200")
    job_data = res_get.get_json()
    _assert(job_data["organization"] == "NIC", "Returns correct job details")

    # 3.2: POST /jobs/<id>/status (Update tracking status & notes)
    update_payload = {
        "user_status": UserStatus.ADMIT_CARD_OUT,
        "notes": "Exam center: New Delhi",
        "registration_number": "NIC-2024-9988",
        "roll_number": "ROLL-12345",
    }
    res_update = client.post("/jobs/1/status", json=update_payload)
    _assert(res_update.status_code == 200, "POST /jobs/1/status returns 200 OK")
    updated_job = res_update.get_json()["job"]
    _assert(updated_job["user_status"] == UserStatus.ADMIT_CARD_OUT, "user_status updated in DB")
    _assert(updated_job["notes"] == "Exam center: New Delhi", "notes updated in DB")
    _assert(updated_job["registration_number"] == "NIC-2024-9988", "registration_number updated")

    # 3.3: POST /jobs/<id>/status with invalid status returns 400
    res_bad_status = client.post("/jobs/1/status", json={"user_status": "InvalidStatus"})
    _assert(res_bad_status.status_code == 400, "Invalid user_status returns HTTP 400 Bad Request")

    # 3.4: POST /fetch-now (Non-blocking background scraper trigger)
    with patch("threading.Thread.start") as mock_thread_start:
        res_fetch = client.post("/fetch-now", headers={"Accept": "application/json"})
        _assert(res_fetch.status_code == 202, "POST /fetch-now returns HTTP 202 Accepted immediately")
        _assert(mock_thread_start.called, "Background daemon thread was started")
        _assert(res_fetch.get_json()["status"] == "started", "Response indicates fetch started")

    # 3.5: POST /sync-calendar (Bulk sync)
    mock_sync_summary = {"synced": 2, "skipped": 1, "errors": 0}
    with patch("calendar_sync.sync_all_jobs", return_value=mock_sync_summary):
        res_bulk_sync = client.post("/sync-calendar", headers={"Accept": "application/json"})
        _assert(res_bulk_sync.status_code == 200, "POST /sync-calendar returns 200 OK")
        _assert(res_bulk_sync.get_json()["summary"]["synced"] == 2, "Bulk sync summary returned")

    # 3.6: POST /jobs/<id>/delete
    res_del = client.post("/jobs/3/delete", headers={"Accept": "application/json"})
    _assert(res_del.status_code == 200, "POST /jobs/3/delete returns 200 OK")
    with app.app_context():
        _assert(db.session.get(Job, 3) is None, "Job #3 deleted from database")


# ============================================================================
# Section 4: Sources Blueprint
# ============================================================================
def test_sources_blueprint():
    section("4. Sources Blueprint (List, Add, Validation, Toggle, Delete)")
    app = setup_test_app()
    client = app.test_client()

    # 4.1: GET /sources (HTML and JSON)
    res_sources_html = client.get("/sources")
    _assert(res_sources_html.status_code == 200, "GET /sources HTML returns 200 OK")
    _assert(b"Government Recruitment Portals" in res_sources_html.data, "HTML contains page title")

    res_sources_json = client.get("/sources", headers={"Accept": "application/json"})
    _assert(res_sources_json.status_code == 200, "GET /sources JSON returns 200 OK")
    sources_data = res_sources_json.get_json()
    _assert(sources_data["total"] == 3, "Returns 3 total sources")
    _assert(sources_data["active_count"] == 2, "Returns 2 active sources")

    # 4.2: POST /sources (Add new portal)
    new_src_payload = {
        "name": "ISRO Careers",
        "url": "https://isro.gov.in/careers",
        "category": ExamCategory.TECHNICAL_CS_IT,
    }
    res_add = client.post("/sources", json=new_src_payload)
    _assert(res_add.status_code == 201, "POST /sources returns 201 Created")
    _assert(res_add.get_json()["source"]["name"] == "ISRO Careers", "New source created in DB")

    # 4.3: POST /sources (Validation: invalid URL without protocol)
    res_invalid_url = client.post("/sources", json={"name": "Bad", "url": "invalid-url"})
    _assert(res_invalid_url.status_code == 400, "Invalid URL returns 400 Bad Request")

    # 4.4: POST /sources (Duplicate URL rejected)
    res_dup = client.post("/sources", json={"name": "Duplicate NIELIT", "url": "https://nielit.gov.in/recruitments"})
    _assert(res_dup.status_code == 409, "Duplicate source URL returns 409 Conflict")

    # 4.5: POST /sources/<id>/toggle
    res_toggle = client.post("/sources/1/toggle", headers={"Accept": "application/json"})
    _assert(res_toggle.status_code == 200, "POST /sources/1/toggle returns 200 OK")
    _assert(res_toggle.get_json()["is_active"] is False, "Active state toggled from True to False")

    # 4.6: POST /sources/<id>/delete
    res_del_src = client.post("/sources/3/delete", headers={"Accept": "application/json"})
    _assert(res_del_src.status_code == 200, "POST /sources/3/delete returns 200 OK")
    with app.app_context():
        _assert(db.session.get(Source, 3) is None, "Source #3 removed from DB")


# ============================================================================
# Section 5: Settings Blueprint
# ============================================================================
def test_settings_blueprint():
    section("5. Settings Blueprint (Profile, Preferences, Telegram Test)")
    app = setup_test_app()
    client = app.test_client()

    # 5.1: GET /settings (HTML and JSON)
    res_settings_html = client.get("/settings")
    _assert(res_settings_html.status_code == 200, "GET /settings HTML returns 200 OK")
    _assert(b"Settings &amp; Integrations" in res_settings_html.data or b"Settings & Integrations" in res_settings_html.data, "HTML contains settings heading")

    res_settings_json = client.get("/settings", headers={"Accept": "application/json"})
    _assert(res_settings_json.status_code == 200, "GET /settings JSON returns 200 OK")
    settings_data = res_settings_json.get_json()
    _assert(settings_data["settings"]["category"] == ReservationCategory.OBC, "Settings reports category OBC")

    # 5.2: POST /settings (Update profile & feature flags)
    update_payload = {
        "date_of_birth": "2000-01-15",
        "category": ReservationCategory.EWS,
        "telegram_bot_token": "updated_bot_tok",
        "telegram_chat_id": "updated_chat_999",
        "feature_flags": {"auto_calendar_sync": True, "telegram_instant_alert": False},
    }
    res_post_settings = client.post("/settings", json=update_payload)
    _assert(res_post_settings.status_code == 200, "POST /settings returns 200 OK")
    with app.app_context():
        s = UserSettings.query.first()
        _assert(s.category == ReservationCategory.EWS, "category updated in database")
        _assert(s.telegram_bot_token == "updated_bot_tok", "telegram_bot_token updated")
        _assert(s.date_of_birth == date(2000, 1, 15), "date_of_birth updated in database")
        flags = json.loads(s.feature_flags)
        _assert(flags.get("auto_calendar_sync") is True, "feature_flags JSON updated in database")

    # 5.3: POST /settings/test-telegram
    with patch("telegram_notifier.send_test_message", return_value=(True, "Test notification delivered.")):
        res_test_tg = client.post("/settings/test-telegram", headers={"Accept": "application/json"})
        _assert(res_test_tg.status_code == 200, "POST /settings/test-telegram returns 200 on success")
        _assert(res_test_tg.get_json()["success"] is True, "test_telegram success=True")


# ============================================================================
# Section 6: Auth Blueprint
# ============================================================================
def test_auth_blueprint():
    section("6. Auth Blueprint (Google OAuth2 Flow & Status)")
    app = setup_test_app()
    client = app.test_client()

    # 6.1: GET /auth/google/status
    with patch("calendar_sync.is_calendar_configured", return_value=True):
        res_status = client.get("/auth/google/status")
        _assert(res_status.status_code == 200, "GET /auth/google/status returns 200 OK")
        _assert(res_status.get_json()["is_connected"] is True, "Reports is_connected=True")

    # 6.2: GET /auth/google when credentials.json missing
    with patch("pathlib.Path.exists", return_value=False):
        res_missing_creds = client.get("/auth/google", headers={"Accept": "application/json"})
        _assert(res_missing_creds.status_code == 404, "GET /auth/google returns 404 when credentials.json missing")
        _assert("credentials.json" in res_missing_creds.get_json()["message"], "Error message explains missing credentials")

    # 6.3: POST /auth/google/disconnect
    res_disc = client.post("/auth/google/disconnect", headers={"Accept": "application/json"})
    _assert(res_disc.status_code == 200, "POST /auth/google/disconnect returns 200 OK")


# ============================================================================
# Section 7: API Blueprint
# ============================================================================
def test_api_blueprint():
    section("7. API Blueprint (REST Endpoints & Metrics)")
    app = setup_test_app()
    client = app.test_client()

    # 7.1: GET /api/health
    res_health = client.get("/api/health")
    _assert(res_health.status_code == 200, "GET /api/health returns 200 OK")
    _assert(res_health.get_json()["status"] == "healthy", "Health status is 'healthy'")

    # 7.2: GET /api/metrics
    res_metrics = client.get("/api/metrics")
    _assert(res_metrics.status_code == 200, "GET /api/metrics returns 200 OK")
    metrics_payload = res_metrics.get_json()["metrics"]
    _assert(metrics_payload["total_jobs"] >= 2, "Metrics reports total jobs")

    # 7.3: GET /api/jobs (with pagination)
    res_jobs = client.get("/api/jobs?limit=2&offset=0")
    _assert(res_jobs.status_code == 200, "GET /api/jobs returns 200 OK")
    jobs_payload = res_jobs.get_json()
    _assert(jobs_payload["limit"] == 2, "Pagination limit applied")
    _assert(len(jobs_payload["jobs"]) <= 2, "Returns at most limit jobs")

    # 7.4: GET /api/sources
    res_api_sources = client.get("/api/sources")
    _assert(res_api_sources.status_code == 200, "GET /api/sources returns 200 OK")
    _assert(res_api_sources.get_json()["total"] >= 2, "Returns sources list")

    # 7.5: POST /api/fetch-now
    with patch("threading.Thread.start"):
        res_api_fetch = client.post("/api/fetch-now")
        _assert(res_api_fetch.status_code == 202, "POST /api/fetch-now returns 202 Accepted")


# ============================================================================
# Section 8: Error Handlers
# ============================================================================
def test_error_handlers():
    section("8. Error Handling (404 JSON for API, HTML for Web)")
    app = setup_test_app()
    client = app.test_client()

    # API 404
    res_api_404 = client.get("/api/nonexistent_endpoint")
    _assert(res_api_404.status_code == 404, "Unknown /api/* route returns 404")
    _assert(res_api_404.is_json, "API 404 response is JSON")

    # Web 404
    res_web_404 = client.get("/nonexistent_page")
    _assert(res_web_404.status_code == 404, "Unknown web route returns 404")
    _assert(b"<!DOCTYPE html>" in res_web_404.data, "Web 404 response renders HTML template")


# ============================================================================
# Main Runner
# ============================================================================
def main():
    print(f"\n{BOLD}{GREEN}================================================================={RESET}")
    print(f"{BOLD}{GREEN}  GovRecruitmentTracker — Milestone 5 Test Suite                 {RESET}")
    print(f"{BOLD}{GREEN}  (Flask Factory, Blueprints & REST API Integration Tests)       {RESET}")
    print(f"{BOLD}{GREEN}================================================================={RESET}")

    test_app_factory()
    test_dashboard_blueprint()
    test_jobs_blueprint()
    test_sources_blueprint()
    test_settings_blueprint()
    test_auth_blueprint()
    test_api_blueprint()
    test_error_handlers()

    print(f"\n{BOLD}{CYAN}{'═'*65}{RESET}")
    print(f"{BOLD}  Milestone 5 Test Results:{RESET}")
    print(f"  Passed: {GREEN}{_pass}{RESET}")
    print(f"  Failed: {RED}{_fail}{RESET}")
    print(f"{BOLD}{CYAN}{'═'*65}{RESET}\n")

    if _fail > 0:
        print(f"{RED}{BOLD}Some tests failed!{RESET}")
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}✓ All Milestone 5 tests passed successfully!{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
