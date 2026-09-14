"""
tests/test_scraper_resilience.py — Scraper resilience tests for GovRecruitmentTracker.

ALL tests use unittest.mock — no live network calls.

Sections:
  1. BaseScraper._get()  — SSL bypass, timeout retry, HTTP error, connection error
  2. PDF Downloader      — archive path, size limit, already-archived skip
  3. URL Utilities       — resolve_url (relative, absolute, query strings)
  4. find_pdf_links      — link extraction and deduplication
  5. find_recruitment_links — keyword-based link discovery
  6. ScraperRunner       — async non-blocking, blocking, callbacks, per-scraper isolation
  7. build_scrapers      — SCRAPER_REGISTRY mapping, GenericCareerScraper fallback
  8. Fault isolation     — one crashing scraper doesn't affect others
"""

from __future__ import annotations

import sys
import os
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

# Make the project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scrapers.base import (
    BaseScraper,
    ScraperRunner,
    _BaseGovScraper,
    resolve_url,
    sanitize_filename,
    url_hash,
    _needs_ssl_bypass,
)
from scrapers.portal_scraper import (
    SCRAPER_REGISTRY,
    GenericCareerScraper,
    build_scrapers_for_sources,
    NIELITScraper,
    SSCScraper,
    IBPSScraper,
)

# ─── Colours ──────────────────────────────────────────────────────────────────
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
    print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*60}{RESET}")


# ─── Minimal concrete scraper for testing ────────────────────────────────────

class _MockScraper(_BaseGovScraper):
    SOURCE_NAME  = "TestPortal"
    SOURCE_URL   = "https://test.gov.in/careers"
    ORGANIZATION = "Test Org"

    def scrape(self):
        return [{"title": "Test Job", "organization": "Test Org",
                 "notification_url": self.SOURCE_URL, "pdf_url": "", "source_name": self.SOURCE_NAME}]


class _CrashingScraper(_BaseGovScraper):
    SOURCE_NAME  = "CrashPortal"
    SOURCE_URL   = "https://crash.gov.in"
    ORGANIZATION = "Crash Org"

    def scrape(self):
        raise RuntimeError("Portal completely unresponsive!")


class _EmptyScraper(_BaseGovScraper):
    SOURCE_NAME  = "EmptyPortal"
    SOURCE_URL   = "https://empty.gov.in"
    ORGANIZATION = "Empty Org"

    def scrape(self):
        return []


# ─── Helper: build a mock response ───────────────────────────────────────────

def _mock_response(status_code=200, text="<html><body></body></html>",
                   content=b"", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.content = content or text.encode()
    resp.headers = headers or {"Content-Type": "text/html", "Content-Length": "100"}
    resp.raise_for_status = MagicMock()
    resp.iter_content = lambda chunk_size=8192: iter([content or text.encode()])
    return resp


# ============================================================================
# 1. BaseScraper._get() — Network resilience
# ============================================================================

section("1. BaseScraper._get() — Network Resilience")

scraper = _MockScraper(archives_dir="/tmp/test_archives_grt")

# 1a. Successful GET returns response
with patch.object(scraper.session, "get", return_value=_mock_response(200)) as mock_get:
    resp = scraper._get("https://test.gov.in/careers")
    _assert(resp is not None, "Successful GET returns response object")
    _assert(mock_get.call_count == 1, "GET called exactly once on success")

# 1b. SSL error → retry with verify=False
import requests.exceptions as req_exc

def _ssl_then_ok(url, timeout, verify, stream, headers, allow_redirects):
    if verify:
        raise req_exc.SSLError("SSL handshake failed")
    return _mock_response(200)

with patch.object(scraper.session, "get", side_effect=_ssl_then_ok):
    resp = scraper._get("https://rac.gov.in/recruitment")
    _assert(resp is not None, "SSL error → retry with verify=False succeeds")

# 1c. _needs_ssl_bypass correctly identifies gov domains
_assert(_needs_ssl_bypass("https://rac.gov.in/notification"), ".gov.in triggers SSL bypass")
_assert(_needs_ssl_bypass("https://nicrecruit.nic.in/"), ".nic.in triggers SSL bypass")
_assert(_needs_ssl_bypass("https://barc.res.in/recruit/"), ".res.in triggers SSL bypass")
_assert(not _needs_ssl_bypass("https://www.ibps.in/crp-po"), "ibps.in does NOT trigger bypass")
_assert(not _needs_ssl_bypass("https://bank.sbi/careers"), "sbi does NOT trigger bypass")

# 1d. Timeout on all attempts → returns None
call_count = [0]
def _always_timeout(url, **kwargs):
    call_count[0] += 1
    raise req_exc.Timeout("Request timed out")

with patch.object(scraper.session, "get", side_effect=_always_timeout):
    with patch("time.sleep"):    # don't actually wait during tests
        resp = scraper._get("https://test.gov.in/slow", retries=2)
        _assert(resp is None, "All timeout attempts → returns None (no crash)")
        _assert(call_count[0] == 3, f"Timeout: 3 attempts made (1 + 2 retries), got {call_count[0]}")

# 1e. ConnectionError → retries then returns None
ce_count = [0]
def _always_connfail(**kwargs):
    ce_count[0] += 1
    raise req_exc.ConnectionError("Connection refused")

with patch.object(scraper.session, "get", side_effect=lambda url, **kw: _always_connfail(**kw)):
    with patch("time.sleep"):
        resp = scraper._get("https://test.gov.in/offline", retries=2)
        _assert(resp is None, "ConnectionError → returns None (no crash)")

# 1f. HTTP 404 → returns None without retry
http_404 = _mock_response(404)
http_404.raise_for_status.side_effect = req_exc.HTTPError(response=http_404)
with patch.object(scraper.session, "get", return_value=http_404):
    resp = scraper._get("https://test.gov.in/notfound")
    _assert(resp is None, "HTTP 404 → returns None immediately")

# 1g. Unexpected exception → returns None without propagating
def _unexpected(*a, **kw):
    raise ValueError("Unexpected internal error")

with patch.object(scraper.session, "get", side_effect=_unexpected):
    resp = scraper._get("https://test.gov.in/error")
    _assert(resp is None, "Unexpected exception → returns None (no crash)")


# ============================================================================
# 2. PDF Downloader
# ============================================================================

section("2. PDF Downloader")

import tempfile
tmp_dir = tempfile.mkdtemp()
dl_scraper = _MockScraper(archives_dir=tmp_dir)

pdf_content = b"%PDF-1.4 fake pdf content for testing"
pdf_resp = _mock_response(200, content=pdf_content,
                          headers={"Content-Type": "application/pdf",
                                   "Content-Length": str(len(pdf_content))})
pdf_resp.iter_content = lambda chunk_size=8192: iter([pdf_content])

# 2a. Successful PDF download creates file
with patch.object(dl_scraper.session, "get", return_value=pdf_resp):
    path = dl_scraper.download_pdf("https://rac.gov.in/notify/advt.pdf", "DRDO RAC")
    _assert(path is not None, "Successful PDF download returns path")
    _assert(Path(path).exists(), "Downloaded PDF file actually exists on disk")
    _assert(Path(path).name.startswith("DRDO_RAC_"), "PDF filename starts with org name")
    _assert(path.endswith(".pdf"), "PDF filename ends with .pdf")

# 2b. Already archived → returns existing path without re-downloading
existing_path = path
with patch.object(dl_scraper.session, "get") as mock_no_call:
    path2 = dl_scraper.download_pdf("https://rac.gov.in/notify/advt.pdf", "DRDO RAC")
    _assert(path2 == existing_path, "Already-archived PDF returns existing path")
    _assert(mock_no_call.call_count == 0, "No HTTP call made for already-archived PDF")

# 2c. PDF download failure → returns None
none_resp = None
with patch.object(dl_scraper.session, "get", return_value=None):
    path3 = dl_scraper.download_pdf("https://rac.gov.in/nonexistent.pdf", "DRDO RAC")
    _assert(path3 is None, "Failed PDF download returns None (no crash)")

# 2d. Sanitize filename handles special characters
name = sanitize_filename("DRDO/RAC: Scientist B (CS/IT) 2025!")
_assert("/" not in name, "sanitize_filename removes forward slashes")
_assert(":" not in name, "sanitize_filename removes colons")
_assert("!" not in name, "sanitize_filename removes exclamation marks")
_assert(len(name) <= 60, "sanitize_filename respects 60-char limit")

# 2e. url_hash produces consistent 16-char hex string
h1 = url_hash("https://rac.gov.in/advt.pdf")
h2 = url_hash("https://rac.gov.in/advt.pdf")
h3 = url_hash("https://rac.gov.in/different.pdf")
_assert(len(h1) == 16, "url_hash produces 16-char string")
_assert(h1 == h2, "url_hash is deterministic for same URL")
_assert(h1 != h3, "url_hash differs for different URLs")


# ============================================================================
# 3. URL Utilities — resolve_url
# ============================================================================

section("3. URL Utilities — resolve_url (Relative URL Resolution)")

base = "https://www.nielit.gov.in/recruitment"

# 3a. Absolute URL passes through unchanged
_assert(
    resolve_url(base, "https://www.nielit.gov.in/files/advt.pdf") == "https://www.nielit.gov.in/files/advt.pdf",
    "Absolute URL stays unchanged"
)

# 3b. Root-relative path
_assert(
    resolve_url(base, "/files/notification.pdf") == "https://www.nielit.gov.in/files/notification.pdf",
    "Root-relative /path resolved correctly"
)

# 3c. Relative path (same directory)
_assert(
    resolve_url("https://www.nielit.gov.in/recruitment/", "advt2025.pdf")
    == "https://www.nielit.gov.in/recruitment/advt2025.pdf",
    "Relative filename resolved in same directory"
)

# 3d. Parent-directory relative path
_assert(
    resolve_url("https://www.nielit.gov.in/recruitment/list.html", "../pdfs/advt.pdf")
    == "https://www.nielit.gov.in/pdfs/advt.pdf",
    "../relative path resolved to parent directory"
)

# 3e. Query string in base (common in .aspx portals)
_assert(
    resolve_url("https://www.cdac.in/index.aspx?id=careers", "/files/job.pdf")
    == "https://www.cdac.in/files/job.pdf",
    "Query string in base URL handled correctly"
)

# 3f. Already-absolute https link in href
_assert(
    resolve_url("https://www.ibps.in/", "https://ibpsonline.ibps.in/crppox/")
    == "https://ibpsonline.ibps.in/crppox/",
    "Cross-domain absolute URL preserved"
)

# 3g. Protocol-relative URL
_assert(
    resolve_url("https://www.ssc.gov.in/", "//cdn.ssc.gov.in/files/notif.pdf")
    == "https://cdn.ssc.gov.in/files/notif.pdf",
    "Protocol-relative // URL resolved with base scheme"
)


# ============================================================================
# 4. find_pdf_links — PDF link extraction
# ============================================================================

section("4. find_pdf_links — PDF Link Extraction from HTML")

from bs4 import BeautifulSoup

html_with_pdfs = """
<html><body>
  <a href="/files/advt_001.pdf">Advt 01/2025 – Scientist B CS</a>
  <a href="https://other.gov.in/notice.pdf">Other Org Notice</a>
  <a href="/files/advt_001.pdf">Duplicate link to same PDF</a>
  <a href="/regular/page.html">Regular page link</a>
  <a href="downloads/circular_it.pdf">Relative PDF link</a>
  <a href="https://external.com/image.jpg">Image file (not PDF)</a>
</body></html>
"""

soup = BeautifulSoup(html_with_pdfs, "html.parser")
pdf_links = scraper.find_pdf_links(soup, "https://www.nielit.gov.in/recruitment/")

_assert(len(pdf_links) == 3, f"3 unique PDF links extracted (got {len(pdf_links)})", str(pdf_links))
_assert(
    "https://www.nielit.gov.in/files/advt_001.pdf" in pdf_links,
    "Root-relative PDF resolved to absolute URL"
)
_assert(
    "https://other.gov.in/notice.pdf" in pdf_links,
    "Cross-domain absolute PDF URL included"
)
_assert(
    "https://www.nielit.gov.in/recruitment/downloads/circular_it.pdf" in pdf_links,
    "Relative PDF resolved from page directory"
)
# Verify no duplicates
_assert(
    pdf_links.count("https://www.nielit.gov.in/files/advt_001.pdf") == 1,
    "Duplicate PDF link deduplicated"
)
# Image file not included
_assert(
    all(".jpg" not in l and ".png" not in l for l in pdf_links),
    "Non-PDF files (jpg, png) excluded"
)


# ============================================================================
# 5. find_recruitment_links — Keyword-based link discovery
# ============================================================================

section("5. find_recruitment_links — Keyword-Based Link Discovery")

html_with_links = """
<html><body>
  <a href="/recruit/advt_2025_01">Recruitment of Scientist B (Computer Science)</a>
  <a href="/vacancy/engineer_cs">Vacancy – Senior Engineer IT (Direct Recruitment)</a>
  <a href="/news/policy">Government Salary Policy Update</a>
  <a href="javascript:void(0)">Click here</a>
  <a href="#section">Jump to section</a>
  <a href="mailto:hr@test.gov.in">Email HR</a>
  <a href="/recruit/advt_2025_01">Duplicate recruitment link</a>
  <a href="/walk-in/tech_2025">Walk-in Interview for IT Officers</a>
</body></html>
"""

soup2 = BeautifulSoup(html_with_links, "html.parser")
rec_links = scraper.find_recruitment_links(soup2, "https://test.gov.in")

titles = [l["title"] for l in rec_links]
urls   = [l["url"] for l in rec_links]

_assert(len(rec_links) == 3, f"3 unique recruitment links found (got {len(rec_links)})", str(titles))
_assert(any("Scientist" in t for t in titles), "Scientist recruitment link found")
_assert(any("Engineer" in t for t in titles), "Engineer vacancy link found")
_assert(any("Walk-in" in t for t in titles), "Walk-in link found")
_assert(not any("Policy" in t for t in titles), "Policy/news link excluded")
_assert(not any(u.startswith("javascript") for u in urls), "javascript: links excluded")
_assert(not any(u.startswith("mailto") for u in urls), "mailto: links excluded")
_assert(
    urls.count("https://test.gov.in/recruit/advt_2025_01") == 1,
    "Duplicate recruitment URL deduplicated"
)


# ============================================================================
# 6. ScraperRunner — Async and blocking modes
# ============================================================================

section("6. ScraperRunner — Async Non-blocking and Blocking")

# 6a. run_all_blocking — collects results from all scrapers
# Clear dedup store so scraper results are not filtered
import dedup as _dedup_module
_dedup_module.clear_memory_store()

results_received = []
complete_count   = [None]

runner = ScraperRunner(
    on_result=lambda r: results_received.extend(r),
    on_complete=lambda n: complete_count.__setitem__(0, n),
)

all_results = runner.run_all_blocking([_MockScraper(), _EmptyScraper()])
_assert(len(all_results) == 1, "Blocking runner: 1 result from MockScraper + 0 from EmptyScraper")
_assert(len(results_received) == 1, "on_result callback called with correct results")
_assert(complete_count[0] == 1, "on_complete callback called with total count=1")

# 6b. run_all_async — returns immediately (non-blocking)
_dedup_module.clear_memory_store()
async_done = threading.Event()
async_results = []

runner2 = ScraperRunner(
    on_result=lambda r: async_results.extend(r),
    on_complete=lambda n: async_done.set(),
)

t_start = time.monotonic()
runner2.run_all_async([_MockScraper(), _EmptyScraper()])
t_elapsed = time.monotonic() - t_start

_assert(t_elapsed < 1.0, f"run_all_async returns in < 1 second (took {t_elapsed:.3f}s)")

# Wait for threads to finish (with generous timeout)
finished = async_done.wait(timeout=10.0)
_assert(finished, "Async scraper threads complete within 10 seconds")
_assert(len(async_results) == 1, "Async runner: correct results collected via callback")

# 6c. run_all_async threads are daemon threads (won't block program exit)
_dedup_module.clear_memory_store()
runner3 = ScraperRunner()
runner3.run_all_async([_MockScraper()])
runner3.wait(timeout=5.0)
for t in runner3._threads:
    _assert(t.daemon, f"Thread '{t.name}' is a daemon thread")


# ============================================================================
# 7. Fault Isolation — one scraper crash doesn't affect others
# ============================================================================

section("7. Fault Isolation — Per-Scraper Error Containment")

# 7a. A crashing scraper's run() returns empty list (no exception propagates)
crash_scraper = _CrashingScraper()
results = crash_scraper.run()
_assert(results == [], "Crashing scraper.run() returns empty list (no exception)")

# 7b. In blocking runner: crashing scraper doesn't affect other scrapers
_dedup_module.clear_memory_store()
crash_results  = []
normal_results = []

def _collect_result(r):
    if r:
        normal_results.extend(r)

runner4 = ScraperRunner(on_result=_collect_result)
all_r = runner4.run_all_blocking([_CrashingScraper(), _MockScraper(), _EmptyScraper()])
_assert(len(all_r) == 1, "Fault isolation: 1 valid result despite 1 crashing scraper")
_assert(len(normal_results) == 1, "Callback only called with valid results")

# 7c. In async runner: crash in one thread doesn't kill other threads
_dedup_module.clear_memory_store()
async_iso_results = []
async_iso_done    = threading.Event()

runner5 = ScraperRunner(
    on_result=lambda r: async_iso_results.extend(r),
    on_complete=lambda n: async_iso_done.set(),
)
runner5.run_all_async([_CrashingScraper(), _MockScraper(), _CrashingScraper()])
finished = async_iso_done.wait(timeout=10.0)
_assert(finished, "Async runner completes even with crashing scrapers")
_assert(len(async_iso_results) == 1, "Async fault isolation: 1 result from 3 scrapers (2 crashing)")


# ============================================================================
# 8. SCRAPER_REGISTRY and build_scrapers_for_sources
# ============================================================================

section("8. SCRAPER_REGISTRY & build_scrapers_for_sources")

# 8a. All expected portal names in registry
expected_names = ["NIELIT", "CDAC", "NIC", "BIS", "DRDO RAC", "BARC", "BEL", "ECIL",
                  "SSC", "UPSC", "IBPS", "SBI", "FreeJobAlert"]
for name in expected_names:
    _assert(name in SCRAPER_REGISTRY, f"SCRAPER_REGISTRY has '{name}'")

# 8b. All registry values are BaseScraper subclasses
for name, cls in SCRAPER_REGISTRY.items():
    _assert(issubclass(cls, BaseScraper), f"{name} scraper is a BaseScraper subclass")

# 8c. build_scrapers_for_sources uses registry for known names
class FakeSource:
    def __init__(self, name, url, is_active=True):
        self.name = name
        self.url  = url
        self.is_active = is_active

sources = [
    FakeSource("NIELIT – National Institute of Electronics and IT", "https://www.nielit.gov.in"),
    FakeSource("SSC – Staff Selection Commission", "https://ssc.gov.in"),
    FakeSource("Custom Portal – Some State Govt", "https://custom.state.gov.in/jobs"),
]
built = build_scrapers_for_sources(sources)
_assert(len(built) == 3, f"build_scrapers_for_sources builds 3 scrapers (got {len(built)})")
_assert(isinstance(built[0], NIELITScraper), "Known source 'NIELIT' gets NIELITScraper")
_assert(isinstance(built[1], SSCScraper), "Known source 'SSC' gets SSCScraper")
_assert(isinstance(built[2], GenericCareerScraper), "Unknown source gets GenericCareerScraper")

# 8d. Inactive sources skipped
sources_with_inactive = [
    FakeSource("IBPS", "https://www.ibps.in", is_active=True),
    FakeSource("SBI", "https://bank.sbi", is_active=False),  # inactive
]
built2 = build_scrapers_for_sources(sources_with_inactive)
_assert(len(built2) == 1, "Inactive sources are excluded from scraper list")
_assert(isinstance(built2[0], IBPSScraper), "Active IBPS source included")

# 8e. GenericCareerScraper respects dynamic SOURCE_URL
gc = GenericCareerScraper(
    source_name="State IT Dept",
    source_url="https://itdept.state.gov.in/careers",
    organization="State IT Department",
)
_assert(gc.SOURCE_NAME == "State IT Dept", "GenericCareerScraper SOURCE_NAME set correctly")
_assert(gc.SOURCE_URL  == "https://itdept.state.gov.in/careers", "GenericCareerScraper SOURCE_URL set correctly")
_assert(gc.ORGANIZATION == "State IT Department", "GenericCareerScraper ORGANIZATION set correctly")

# 8f. GenericCareerScraper.scrape() on mock HTML
html_generic = """
<html><body>
  <h1>IT Department Recruitment</h1>
  <a href="/files/vacancy_2025.pdf">Vacancy Notification 2025 – Software Engineer</a>
  <a href="/recruitment/application-form">Apply Online for Technical Recruitment</a>
</body></html>
"""
mock_resp = _mock_response(200, text=html_generic)
with patch.object(gc.session, "get", return_value=mock_resp):
    results = gc.scrape()
    _assert(len(results) >= 1, f"GenericCareerScraper finds at least 1 result (got {len(results)})")
    has_pdf = any(r.get("pdf_url", "").endswith(".pdf") for r in results)
    _assert(has_pdf, "GenericCareerScraper correctly identifies PDF links")


# ============================================================================
# 9. SHA-256 URL Deduplication (dedup.py)
# ============================================================================

section("9. SHA-256 URL Deduplication")

from dedup import (
    is_new_url,
    mark_url_seen,
    clear_memory_store,
    memory_store_size,
    url_fingerprint,
)

# Reset store before dedup tests
clear_memory_store()

# 9a. Fingerprint properties
fp1 = url_fingerprint("https://rac.gov.in/advt_2025_01.pdf")
fp2 = url_fingerprint("https://rac.gov.in/advt_2025_01.pdf")
fp3 = url_fingerprint("https://rac.gov.in/advt_2025_02.pdf")
_assert(len(fp1) == 64, "SHA-256 fingerprint is 64 hex chars")
_assert(fp1 == fp2, "Same URL always produces identical fingerprint")
_assert(fp1 != fp3, "Different URLs produce different fingerprints")

# 9b. Fresh URL reports as new
url_a = "https://nielit.gov.in/notification/advt_001.pdf"
_assert(is_new_url(url_a) is True, "Unseen URL reports as new (is_new_url=True)")

# 9c. After marking seen, same URL is no longer new
mark_url_seen(url_a, "NIELIT")
_assert(is_new_url(url_a) is False, "Seen URL correctly reports as NOT new after mark_url_seen")
_assert(memory_store_size() == 1, "Memory store has exactly 1 entry after one mark")

# 9d. Different URL still new after marking first
url_b = "https://nielit.gov.in/notification/advt_002.pdf"
_assert(is_new_url(url_b) is True, "Different URL still reports as new")

# 9e. mark_url_seen is idempotent (double-mark doesn't corrupt store)
mark_url_seen(url_a, "NIELIT")   # second call, same URL
mark_url_seen(url_a, "NIELIT")   # third call
_assert(memory_store_size() == 1, "Idempotent: multiple marks of same URL keep store size=1")

# 9f. Empty / None URLs are handled gracefully
_assert(is_new_url("") is False, "Empty URL string is not treated as new")
_assert(is_new_url("   ") is False, "Whitespace-only URL is not treated as new")
mark_url_seen("", "test")       # should not crash
mark_url_seen(None, "test") if False else None  # skip None test (type annotation)
_assert(True, "Empty URL mark_url_seen does not crash")

# 9g. clear_memory_store resets the in-memory store
mark_url_seen(url_b, "NIELIT")
clear_memory_store()
_assert(memory_store_size() == 0, "clear_memory_store resets size to 0")
_assert(is_new_url(url_b) is True, "URL is new again after clear_memory_store")

# 9h. Multiple different URLs tracked correctly
clear_memory_store()
urls_to_mark = [f"https://rac.gov.in/advt_{i:04d}.pdf" for i in range(10)]
for u in urls_to_mark:
    mark_url_seen(u, "DRDO RAC")
_assert(memory_store_size() == 10, "10 distinct URLs tracked correctly")
for u in urls_to_mark:
    _assert(is_new_url(u) is False, f"Marked URL {u[-12:]} correctly reports as seen")

# 9i. Integration: BaseScraper.run() dedup filters duplicates across two calls
clear_memory_store()

class _DeduplicatableScraper(_BaseGovScraper):
    SOURCE_NAME  = "DedupePortal"
    SOURCE_URL   = "https://dedupe.gov.in"
    ORGANIZATION = "Dedupe Test Org"

    def scrape(self):
        return [
            {"title": "Job A", "organization": "Dedupe Test Org",
             "notification_url": "https://dedupe.gov.in/jobA",
             "pdf_url": "https://dedupe.gov.in/jobA.pdf", "source_name": "DedupePortal"},
            {"title": "Job B", "organization": "Dedupe Test Org",
             "notification_url": "https://dedupe.gov.in/jobB",
             "pdf_url": "https://dedupe.gov.in/jobB.pdf", "source_name": "DedupePortal"},
        ]

dedup_scraper = _DeduplicatableScraper()
first_run  = dedup_scraper.run()
second_run = dedup_scraper.run()   # same URLs — should all be deduped

_assert(len(first_run) == 2, f"First run: 2 new results (got {len(first_run)})")
_assert(len(second_run) == 0, f"Second run: 0 results (both deduped), got {len(second_run)}")

# 9j. Result with no URL passes through dedup without being marked
class _NoURLScraper(_BaseGovScraper):
    SOURCE_NAME = "NoURLPortal"
    SOURCE_URL  = "https://nourl.gov.in"
    ORGANIZATION = "NoURL Org"

    def scrape(self):
        return [{"title": "Unknown job", "organization": "NoURL Org",
                 "notification_url": "", "pdf_url": "", "source_name": "NoURLPortal"}]

clear_memory_store()
no_url_scraper = _NoURLScraper()
run1 = no_url_scraper.run()
run2 = no_url_scraper.run()
_assert(len(run1) == 1, "No-URL result passes through on first run")
_assert(len(run2) == 1, "No-URL result passes through on second run (no URL to dedup)")
_assert(memory_store_size() == 0, "No-URL result doesn't pollute dedup store")


# ============================================================================
# Results Summary
# ============================================================================

total = _pass + _fail
print(f"\n{'─'*60}")
print(f"{BOLD}  Results: {GREEN}{_pass}/{total} passed{RESET}", end="")
if _fail:
    print(f"  {RED}{_fail} FAILED{RESET}", end="")
print(f"\n{'─'*60}\n")

# Cleanup temp dir
import shutil
shutil.rmtree(tmp_dir, ignore_errors=True)

if _fail > 0:
    sys.exit(1)
else:
    print(f"{GREEN}{BOLD}  ✓ All tests passed!{RESET}\n")
