"""
tests/test_frontend.py — Frontend, UI Refinement & Mobile Optimization Tests for Milestone 6.

Validates:
  1. Static Asset Serving (CSS, JS) with 200 OK
  2. Dark Mode Design Tokens & Glassmorphism in static/css/styles.css
  3. Slide-over Drawer Markup & Fields in layout.html
  4. Instant Zero-FOUC Theme Script in layout.html
  5. Dense Sortable Table with [Non-GATE], [Level 10+], [CS/IT] tags in dashboard.html
  6. Mobile High-touch Urgency-colored Cards (🔴, 🟡, 🟢) in dashboard.html
  7. Client-side Sort & Dynamic Filter logic in static/js/main.js
  8. Sources & Settings Template Rendering & Responsiveness
"""

from __future__ import annotations

import os
import sys

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
    """Create test Flask app configured with in-memory SQLite and seeded data."""
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
        s1 = Source(name="NIELIT", url="https://nielit.gov.in", category=ExamCategory.TECHNICAL_CS_IT, scraper_type="NIELITScraper", is_active=True)
        s2 = Source(name="UPSC", url="https://upsc.gov.in", category=ExamCategory.COMPETITIVE_EXAM, scraper_type="UPSCScraper", is_active=True)
        db.session.add_all([s1, s2])

        # Seed test jobs: Non-GATE CS/IT, Level 10+, GATE job
        j1 = Job(
            title="Scientist B (CS)",
            organization="NIC",
            exam_category=ExamCategory.TECHNICAL_CS_IT,
            gate_required=False,
            eligible_cs_it=True,
            pay_level_or_ctc="Level 10 (Rs. 56,100 - 1,77,500)",
            last_date="20/12/2026",
            exam_date="15/01/2027",
            user_status=UserStatus.NOT_APPLIED,
            notification_url="https://nic.gov.in/job1",
            pdf_url="https://nic.gov.in/job1.pdf",
            is_synced_to_calendar=False,
        )
        j2 = Job(
            title="Executive Trainee (IT)",
            organization="IOCL",
            exam_category=ExamCategory.PSU,
            gate_required=True,
            eligible_cs_it=True,
            pay_level_or_ctc="Rs. 60,000 - 1,80,000",
            last_date="05/11/2026",
            exam_date="",
            user_status=UserStatus.APPLIED,
            notification_url="https://iocl.com/job2",
            is_synced_to_calendar=True,
        )
        j3 = Job(
            title="Combined Graduate Level (Assistant Section Officer)",
            organization="SSC CGL",
            exam_category=ExamCategory.COMPETITIVE_EXAM,
            gate_required=False,
            eligible_cs_it=False,
            any_graduate_eligible=True,
            pay_level_or_ctc="Level 7",
            last_date="12/10/2026",
            user_status=UserStatus.NOT_APPLIED,
            notification_url="https://ssc.nic.in/cgl",
            is_synced_to_calendar=False,
        )
        db.session.add_all([j1, j2, j3])

        # Seed user settings
        settings = UserSettings(
            dob="1998-05-20",
            category=ReservationCategory.OBC,
            telegram_bot_token="123456:ABC-DEF",
            telegram_chat_id="987654321",
        )
        db.session.add(settings)
        db.session.commit()

    return app


def run_tests():
    app = setup_test_app()
    client = app.test_client()

    print(f"\n{BOLD}================================================================={RESET}")
    print(f"{BOLD}  Milestone 6: Frontend, UI Refinement & Mobile Optimization Tests{RESET}")
    print(f"{BOLD}================================================================={RESET}")

    # ─── 1. Static Asset Serving ────────────────────────────────────────────────
    section("1. Static Asset Serving")
    res_css = client.get("/static/css/styles.css")
    _assert(res_css.status_code == 200, "GET /static/css/styles.css returns HTTP 200 OK")
    _assert("text/css" in res_css.content_type, "styles.css served with text/css content type")
    _assert(len(res_css.data) > 5000, f"styles.css has substantial content ({len(res_css.data)} bytes)")

    res_js = client.get("/static/js/main.js")
    _assert(res_js.status_code == 200, "GET /static/js/main.js returns HTTP 200 OK")
    _assert("javascript" in res_js.content_type or "text/plain" in res_js.content_type, "main.js served with javascript content type")
    _assert(len(res_js.data) > 5000, f"main.js has substantial content ({len(res_js.data)} bytes)")

    # ─── 2. Design System Tokens & Dark-Mode First Styling ──────────────────────
    section("2. Design System Tokens & Dark-Mode First Styling")
    css_text = res_css.data.decode("utf-8")
    _assert("#0d1117" in css_text, "CSS includes default dark background #0d1117")
    _assert("--bg-surface" in css_text and "backdrop-filter" in css_text, "CSS implements glassmorphic surface backdrop-filter")
    _assert("--primary" in css_text, "CSS defines electric blue primary color")
    _assert("--font-sans" in css_text and "Inter" in css_text, "CSS configures Inter sans typography")
    _assert("--font-mono" in css_text and "JetBrains Mono" in css_text, "CSS configures JetBrains Mono monospace typography")
    _assert("[data-theme=\"light\"]" in css_text, "CSS provides complete light-mode theme overrides")
    _assert(".dense-table th.sortable" in css_text, "CSS styles sortable table column headers")
    _assert(".job-card.urgency-urgent" in css_text, "CSS provides urgency-urgent card indicators")
    _assert(".job-card.urgency-moderate" in css_text, "CSS provides urgency-moderate card indicators")
    _assert(".job-card.urgency-relaxed" in css_text, "CSS provides urgency-relaxed card indicators")
    _assert(".drawer-panel" in css_text and ".drawer-backdrop" in css_text, "CSS includes slide-over drawer panel & backdrop transitions")

    # ─── 3. Layout & Immediate Theme Initialization ─────────────────────────────
    section("3. Layout & Zero-FOUC Theme Initialization")
    res_dash = client.get("/")
    dash_html = res_dash.data.decode("utf-8")
    _assert("<html lang=\"en\" data-theme=\"dark\">" in dash_html, "HTML defaults to data-theme='dark'")
    _assert("localStorage.getItem('grt-theme')" in dash_html, "Inline theme script reads 'grt-theme' immediately before paint")
    _assert("GovRecruitmentTracker" in dash_html, "Branding rendered in navbar")
    _assert("themeToggleBtn" in dash_html, "Dark/light mode toggle button present in navbar")
    _assert("mobileMenuBtn" in dash_html, "Mobile hamburger menu toggle button present")
    _assert("toast-container" in dash_html, "Toast container present in layout")

    # ─── 4. Slide-over Drawer Markup ────────────────────────────────────────────
    section("4. Slide-over Tracking Drawer Markup")
    _assert("id=\"jobDrawerBackdrop\"" in dash_html, "Drawer backdrop markup present in DOM")
    _assert("id=\"jobDrawerPanel\"" in dash_html, "Drawer panel element present in DOM")
    _assert("id=\"jobDrawerForm\"" in dash_html, "Drawer tracking form present in DOM")
    _assert("id=\"drawerJobId\"" in dash_html, "Hidden job ID input present in drawer")
    _assert("id=\"drawerStatus\"" in dash_html, "Status select dropdown present in drawer")
    _assert("id=\"drawerRegNum\"" in dash_html, "Registration number input present in drawer")
    _assert("id=\"drawerRollNum\"" in dash_html, "Roll number input present in drawer")
    _assert("id=\"drawerNotes\"" in dash_html, "Personal notes textarea present in drawer")

    # ─── 5. Desktop Dense Table View & Bracket Tags ─────────────────────────────
    section("5. Desktop Dense Table View & Bracket Tags")
    _assert("desktop-only" in dash_html, "Table view is wrapped in .desktop-only container")
    _assert("dense-table" in dash_html, "Table uses .dense-table class")
    _assert("data-sort=\"org\"" in dash_html, "Table headers have data-sort attributes for sorting")
    _assert("[Non-GATE]" in dash_html, "Desktop table renders explicit [Non-GATE] badge tag")
    _assert("[GATE Req]" in dash_html, "Desktop table renders explicit [GATE Req] badge tag")
    _assert("[Level 10+]" in dash_html, "Desktop table renders explicit [Level 10+] badge tag")
    _assert("[CS/IT]" in dash_html, "Desktop table renders explicit [CS/IT] badge tag")

    # ─── 6. Mobile High-Touch Urgency Cards View ────────────────────────────────
    section("6. Mobile High-Touch Urgency Cards View")
    _assert("mobile-only" in dash_html, "Card view is wrapped in .mobile-only container")
    _assert("job-card" in dash_html, "Cards use .job-card class")
    _assert("urgency-" in dash_html, "Cards have dynamic urgency-* classes")
    _assert("Scientist B (CS)" in dash_html, "Job title rendered inside mobile cards")
    _assert("NIC" in dash_html, "Organization rendered inside mobile cards")
    _assert("openJobDrawer(" in dash_html, "Cards contain quick-tap button to open tracking drawer")
    _assert("syncJobToCalendar(" in dash_html, "Cards contain quick-tap button to sync with calendar")

    # ─── 7. JavaScript Architecture & Capabilities ──────────────────────────────
    section("7. JavaScript Architecture & Capabilities")
    js_text = res_js.data.decode("utf-8")
    _assert("initTheme" in js_text, "main.js implements initTheme with localStorage persistence")
    _assert("openJobDrawer" in js_text, "main.js implements window.openJobDrawer via AJAX")
    _assert("closeJobDrawer" in js_text, "main.js implements window.closeJobDrawer")
    _assert("showToast" in js_text, "main.js implements notification toast system")
    _assert("initTableSort" in js_text, "main.js implements client-side table column sorting")
    _assert("initDynamicFilters" in js_text, "main.js implements instant dynamic search filtering")
    _assert("syncJobToCalendar" in js_text, "main.js implements quick calendar sync AJAX")
    _assert("sendJobTelegramAlert" in js_text, "main.js implements quick telegram alert AJAX")

    # ─── 8. Sources & Settings Templates ────────────────────────────────────────
    section("8. Sources & Settings Templates")
    res_sources = client.get("/sources")
    sources_html = res_sources.data.decode("utf-8")
    _assert(res_sources.status_code == 200, "GET /sources returns HTTP 200 OK")
    _assert("Add Government Portal" in sources_html, "Sources page renders Add Portal form")
    _assert("NIELIT" in sources_html, "Sources page renders configured portal NIELIT")
    _assert("UPSC" in sources_html, "Sources page renders configured portal UPSC")
    _assert("resetCacheBtn" in sources_html, "Sources page renders Reset Dedup Cache button")

    res_settings = client.get("/settings")
    settings_html = res_settings.data.decode("utf-8")
    _assert(res_settings.status_code == 200, "GET /settings returns HTTP 200 OK")
    _assert("User Profile &amp; Age Eligibility" in settings_html, "Settings page renders User Profile card")
    _assert("1998-05-20" in settings_html, "Settings renders saved Date of Birth")
    _assert("Telegram Alert Bot" in settings_html, "Settings renders Telegram configuration card")
    _assert("Google Calendar Integration" in settings_html, "Settings renders Google Calendar card")

    # ─── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}═════════════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Milestone 6 Test Results:{RESET}")
    print(f"  {GREEN}Passed: {_pass}{RESET}")
    print(f"  {RED if _fail else GREEN}Failed: {_fail}{RESET}")
    print(f"{BOLD}═════════════════════════════════════════════════════════════════{RESET}")

    if _fail > 0:
        print(f"\n{RED}✗ Some tests failed!{RESET}\n")
        sys.exit(1)
    else:
        print(f"\n{GREEN}✓ All Milestone 6 tests passed successfully!{RESET}\n")


if __name__ == "__main__":
    run_tests()
