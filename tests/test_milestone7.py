"""
tests/test_milestone7.py — Production Deployment Readiness & iCal Feed Verification.

Covers:
  1. iCal (.ics) Dynamic Subscription Feed (RFC 5545 compliance, VEVENT, VALARM reminders)
  2. Deployment Configuration Integrity (Procfile, render.yaml, gunicorn_config.py)
  3. Git Configuration & Secrets Protection (.gitignore)
  4. Documentation & Deployment Guides (README.md)
"""

from __future__ import annotations

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from models import ExamCategory, Job, db

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


def run_tests():
    print(f"\n{BOLD}================================================================={RESET}")
    print(f"{BOLD}  Milestone 7: Production Deployment & iCal Feed Verification{RESET}")
    print(f"{BOLD}================================================================={RESET}")

    base_dir = os.path.dirname(os.path.dirname(__file__))

    # ─── 1. Deployment Files Verification ────────────────────────────────────────
    section("1. Deployment Files Verification")

    procfile_path = os.path.join(base_dir, "Procfile")
    _assert(os.path.exists(procfile_path), "Procfile exists in project root")
    with open(procfile_path, "r", encoding="utf-8") as f:
        procfile_content = f.read()
    _assert("gunicorn app:app" in procfile_content, "Procfile invokes gunicorn app:app")
    _assert("gunicorn_config.py" in procfile_content, "Procfile specifies gunicorn_config.py")

    render_path = os.path.join(base_dir, "render.yaml")
    _assert(os.path.exists(render_path), "render.yaml exists in project root")
    with open(render_path, "r", encoding="utf-8") as f:
        render_content = f.read()
    _assert("type: web" in render_content, "render.yaml defines a web service")
    _assert("plan: free" in render_content, "render.yaml specifies free plan")
    _assert("flask init-db" in render_content, "render.yaml buildCommand runs database seeding")
    _assert("gunicorn app:app" in render_content, "render.yaml startCommand starts Gunicorn")
    _assert("GEMINI_API_KEY" in render_content, "render.yaml includes GEMINI_API_KEY envVar")
    _assert("DATABASE_URL" in render_content, "render.yaml includes DATABASE_URL envVar")

    gunicorn_path = os.path.join(base_dir, "gunicorn_config.py")
    _assert(os.path.exists(gunicorn_path), "gunicorn_config.py exists in project root")
    with open(gunicorn_path, "r", encoding="utf-8") as f:
        gunicorn_content = f.read()
    _assert("0.0.0.0" in gunicorn_content, "gunicorn_config binds to 0.0.0.0")
    _assert("PORT" in gunicorn_content, "gunicorn_config reads PORT environment variable")
    _assert("gthread" in gunicorn_content, "gunicorn_config uses gthread concurrency")

    # ─── 2. Git & Secrets Protection ────────────────────────────────────────────
    section("2. Git & Secrets Protection")

    gitignore_path = os.path.join(base_dir, ".gitignore")
    _assert(os.path.exists(gitignore_path), ".gitignore exists in project root")
    with open(gitignore_path, "r", encoding="utf-8") as f:
        gi_content = f.read()
    _assert(".venv/" in gi_content, ".gitignore excludes virtual environment .venv/")
    _assert("credentials.json" in gi_content, ".gitignore protects OAuth credentials.json")
    _assert("token.json" in gi_content, ".gitignore protects authorized token.json")
    _assert(".env" in gi_content, ".gitignore protects local .env files")
    _assert("*.db" in gi_content, ".gitignore excludes local database files")

    # ─── 3. Documentation Completeness ──────────────────────────────────────────
    section("3. Documentation Completeness")

    readme_path = os.path.join(base_dir, "README.md")
    _assert(os.path.exists(readme_path), "README.md exists in project root")
    with open(readme_path, "r", encoding="utf-8") as f:
        readme_content = f.read()
    _assert("GitHub Setup" in readme_content, "README contains GitHub push instructions")
    _assert("Render (Free Tier)" in readme_content, "README contains Render deployment instructions")
    _assert("Environment Variables" in readme_content, "README contains environment variables table")
    _assert("calendar.ics" in readme_content, "README explains iCal calendar feed subscription")

    # ─── 4. iCal (.ics) Dynamic Feed Route & Compliance ─────────────────────────
    section("4. iCal (.ics) Dynamic Feed Route & Compliance")

    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SECRET_KEY": "test-key-deployment",
        "ARCHIVES_DIR": "/tmp/grt_test_archives",
    }
    app = create_app(test_config)

    with app.app_context():
        db.create_all()

        j1 = Job(
            title="Scientist B (CS)",
            organization="NIC",
            exam_category=ExamCategory.TECHNICAL_CS_IT,
            gate_required=False,
            last_date="20/12/2026",
            exam_date="15/01/2027",
            notification_url="https://nic.gov.in/job1",
        )
        j2 = Job(
            title="Assistant Manager (IT)",
            organization="NABARD",
            exam_category=ExamCategory.BANKING,
            gate_required=False,
            last_date="10/11/2026",
            exam_date="",
            notification_url="https://nabard.org/careers",
        )
        db.session.add_all([j1, j2])
        db.session.commit()

        client = app.test_client()

        # Test GET /calendar.ics
        res = client.get("/calendar.ics")
        _assert(res.status_code == 200, "GET /calendar.ics returns HTTP 200 OK")
        _assert("text/calendar" in res.content_type, "Response Content-Type is text/calendar")
        _assert("attachment" in res.headers.get("Content-Disposition", "") or "inline" in res.headers.get("Content-Disposition", ""), "Content-Disposition header is present")

        feed_text = res.data.decode("utf-8")
        _assert("BEGIN:VCALENDAR" in feed_text and "END:VCALENDAR" in feed_text, "Feed begins and ends with VCALENDAR")
        _assert("VERSION:2.0" in feed_text, "Feed specifies RFC 5545 VERSION:2.0")
        _assert("X-WR-CALNAME:Gov Recruitment Deadlines" in feed_text, "Feed contains calendar name")
        _assert("BEGIN:VEVENT" in feed_text, "Feed contains VEVENT elements")
        _assert("UID:grt-job-1-deadline@govrecruitmenttracker" in feed_text, "Feed contains stable individual event UID")
        _assert("BEGIN:VALARM" in feed_text, "Feed contains VALARM reminder alarms")
        _assert("TRIGGER:-P3D" in feed_text, "Feed includes 3-day reminder trigger")
        _assert("TRIGGER:-P1D" in feed_text, "Feed includes 1-day urgent reminder trigger")
        _assert("UID:grt-job-1-exam@govrecruitmenttracker" in feed_text, "Feed creates separate exam event when exam_date present")
        _assert("TRIGGER:-P7D" in feed_text, "Exam event includes 7-day reminder trigger")

        # Test alternate feed route /calendar/feed.ics
        res_alt = client.get("/calendar/feed.ics")
        _assert(res_alt.status_code == 200, "GET /calendar/feed.ics returns HTTP 200 OK")

    # ─── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}═════════════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Milestone 7 Test Results:{RESET}")
    print(f"  {GREEN}Passed: {_pass}{RESET}")
    print(f"  {RED if _fail else GREEN}Failed: {_fail}{RESET}")
    print(f"{BOLD}═════════════════════════════════════════════════════════════════{RESET}")

    if _fail > 0:
        print(f"\n{RED}✗ Some tests failed!{RESET}\n")
        sys.exit(1)
    else:
        print(f"\n{GREEN}✓ All Milestone 7 tests passed successfully!{RESET}\n")


if __name__ == "__main__":
    run_tests()
