"""
scrapers/base.py — BaseScraper ABC and ScraperRunner for GovRecruitmentTracker.

Design principles:
  - Every concrete scraper extends BaseScraper and implements scrape() -> list[dict].
  - All HTTP goes through _get() which handles: realistic headers, SSL bypass,
    15-second timeout, 2 retries with exponential backoff.
  - PDF archiving downloads to archives/{org}_{hash}.pdf with sanitized filenames.
  - ScraperRunner fires each scraper in a daemon threading.Thread so POST /fetch-now
    returns immediately without blocking the web request.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import urllib.parse
from abc import ABC, abstractmethod
from pathlib import Path
from threading import Thread, Event
from typing import Any, Callable

import requests
import urllib3
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ─── Suppress InsecureRequestWarning for .gov.in / .nic.in SSL issues ────────
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Realistic Chrome/Edge browser headers ───────────────────────────────────
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

# ─── Domain groups that commonly have SSL issues ──────────────────────────────
_SSL_BYPASS_DOMAINS = (
    ".gov.in", ".nic.in", ".res.in",
    "rac.gov.in", "barc.gov.in", "ecil.co.in",
)

DEFAULT_TIMEOUT  = 15      # seconds
DEFAULT_RETRIES  = 2
BACKOFF_BASE     = 1.5     # seconds; doubled each retry
MAX_ARCHIVE_SIZE = 50      # MB; skip PDFs larger than this


def sanitize_filename(text: str) -> str:
    """Convert arbitrary string to a safe filesystem filename segment."""
    text = re.sub(r"[^\w\s\-]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:60]


def url_hash(url: str) -> str:
    """Return first 16 chars of SHA-256 of URL (for filenames and dedup keys)."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def resolve_url(base_url: str, href: str) -> str:
    """Resolve a possibly-relative href against a base URL."""
    return urllib.parse.urljoin(base_url, href)


def _needs_ssl_bypass(url: str) -> bool:
    """Return True if the URL is known to have SSL verification issues."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in _SSL_BYPASS_DOMAINS)


# ============================================================================
# BaseScraper — Abstract base class
# ============================================================================

class BaseScraper(ABC):
    """
    Abstract base for all portal scrapers.

    Subclasses must define:
        SOURCE_NAME: str   — Human-readable portal name.
        SOURCE_URL:  str   — The career / recruitment page URL.
        scrape()           — Return list of raw job dicts.

    Each raw job dict should contain at minimum:
        {
          "title":            str,   # Post/exam name (may be empty)
          "organization":     str,   # Hiring org
          "notification_url": str,   # Link to the full notice page
          "pdf_url":          str,   # Direct PDF link (may be empty)
          "source_name":      str,   # Same as SOURCE_NAME
        }
    """

    SOURCE_NAME: str = ""
    SOURCE_URL:  str = ""

    def __init__(self, archives_dir: str = "archives", config: dict | None = None):
        self.archives_dir = Path(archives_dir)
        self.archives_dir.mkdir(parents=True, exist_ok=True)
        self.config = config or {}
        self.session = self._build_session()

    # ── HTTP Session ──────────────────────────────────────────────────────────

    def _build_session(self) -> requests.Session:
        """Build a requests.Session with browser headers and retry adapter."""
        session = requests.Session()
        session.headers.update(_BROWSER_HEADERS)
        # Mount retry adapter for both http and https
        adapter = requests.adapters.HTTPAdapter(max_retries=0)   # we handle retries manually
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _get(
        self,
        url: str,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        stream: bool = False,
        extra_headers: dict | None = None,
    ) -> requests.Response | None:
        """
        Resilient GET with:
          - SSL bypass for .gov.in / .nic.in domains.
          - Up to `retries` attempts with exponential backoff.
          - 15-second timeout (connect + read).
          - Returns None on all failures (never raises).

        Each portal that fails is isolated; one down portal never crashes
        the entire scraper pipeline.
        """
        verify = not _needs_ssl_bypass(url)
        headers = extra_headers or {}

        for attempt in range(retries + 1):
            try:
                resp = self.session.get(
                    url,
                    timeout=timeout,
                    verify=verify,
                    stream=stream,
                    headers=headers,
                    allow_redirects=True,
                )
                resp.raise_for_status()
                return resp

            except requests.exceptions.SSLError:
                if verify:
                    # First SSL failure → retry with verify=False
                    logger.warning("[%s] SSL error on %s — retrying without verification.", self.SOURCE_NAME, url)
                    verify = False
                    continue
                logger.error("[%s] SSL error persists on %s even with bypass.", self.SOURCE_NAME, url)
                return None

            except requests.exceptions.Timeout:
                wait = BACKOFF_BASE * (2 ** attempt)
                logger.warning("[%s] Timeout on %s (attempt %d/%d) — waiting %.1fs.",
                               self.SOURCE_NAME, url, attempt + 1, retries + 1, wait)
                if attempt < retries:
                    time.sleep(wait)

            except requests.exceptions.ConnectionError as exc:
                wait = BACKOFF_BASE * (2 ** attempt)
                logger.warning("[%s] ConnectionError on %s (attempt %d/%d): %s",
                               self.SOURCE_NAME, url, attempt + 1, retries + 1, exc)
                if attempt < retries:
                    time.sleep(wait)

            except requests.exceptions.HTTPError as exc:
                logger.warning("[%s] HTTP %s for %s — skipping.", self.SOURCE_NAME, exc.response.status_code, url)
                return None

            except Exception as exc:
                logger.error("[%s] Unexpected error fetching %s: %s", self.SOURCE_NAME, url, exc)
                return None

        logger.error("[%s] All %d attempts failed for %s.", self.SOURCE_NAME, retries + 1, url)
        return None

    def get_soup(self, url: str, **kwargs) -> BeautifulSoup | None:
        """Fetch URL and return a BeautifulSoup object (html.parser). None on failure."""
        resp = self._get(url, **kwargs)
        if resp is None:
            return None
        try:
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as exc:
            logger.error("[%s] Could not parse HTML from %s: %s", self.SOURCE_NAME, url, exc)
            return None

    # ── PDF Archiver ──────────────────────────────────────────────────────────

    def download_pdf(self, pdf_url: str, org_name: str = "", job_id: str = "") -> str | None:
        """
        Download a PDF to the archives directory.

        Filename format: {org}_{hash}.pdf
        Returns local path string on success, None on failure.

        Skips files larger than MAX_ARCHIVE_SIZE MB.
        """
        org_part  = sanitize_filename(org_name or self.SOURCE_NAME or "gov")
        hash_part = url_hash(pdf_url)
        filename  = f"{org_part}_{hash_part}.pdf"
        dest      = self.archives_dir / filename

        if dest.exists():
            logger.debug("[%s] PDF already archived: %s", self.SOURCE_NAME, dest)
            return str(dest)

        logger.info("[%s] Downloading PDF: %s", self.SOURCE_NAME, pdf_url)
        resp = self._get(
            pdf_url,
            timeout=30,
            stream=True,
            extra_headers={"Accept": "application/pdf,*/*"},
        )
        if resp is None:
            return None

        # Check content-length before writing
        content_length = resp.headers.get("Content-Length", "0")
        try:
            size_mb = int(content_length) / (1024 * 1024)
            if size_mb > MAX_ARCHIVE_SIZE:
                logger.warning("[%s] PDF too large (%.1fMB > %dMB limit): %s",
                               self.SOURCE_NAME, size_mb, MAX_ARCHIVE_SIZE, pdf_url)
                return None
        except (ValueError, TypeError):
            pass

        try:
            with open(dest, "wb") as f:
                downloaded = 0
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded > MAX_ARCHIVE_SIZE * 1024 * 1024:
                            logger.warning("[%s] PDF exceeded size limit mid-download — truncating.", self.SOURCE_NAME)
                            break
            logger.info("[%s] PDF saved: %s (%.1f KB)", self.SOURCE_NAME, dest, dest.stat().st_size / 1024)
            return str(dest)
        except Exception as exc:
            logger.error("[%s] Failed to write PDF %s: %s", self.SOURCE_NAME, dest, exc)
            dest.unlink(missing_ok=True)
            return None

    # ── HTML Link Utilities ───────────────────────────────────────────────────

    def find_pdf_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Extract all PDF anchor hrefs from a BeautifulSoup page, resolved to absolute URLs."""
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.lower().endswith(".pdf") or "pdf" in href.lower():
                links.append(resolve_url(base_url, href))
        return list(dict.fromkeys(links))   # deduplicate, preserve order

    def find_recruitment_links(
        self,
        soup: BeautifulSoup,
        base_url: str,
        keywords: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """
        Find anchor tags whose text contains recruitment-related keywords.

        Returns list of {"title": str, "url": str}
        """
        keywords = keywords or [
            "recruitment", "vacancy", "notification", "advt", "advertisement",
            "career", "job", "post", "walk-in", "interview", "scientist",
            "engineer", "officer", "assistant", "clerk", "probationary",
        ]
        pattern = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)
        results = []
        seen = set()
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"].strip()
            if not text or not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            abs_url = resolve_url(base_url, href)
            if abs_url in seen:
                continue
            if pattern.search(text) or pattern.search(href):
                seen.add(abs_url)
                results.append({"title": text[:200], "url": abs_url})
        return results

    # ── Abstract method ───────────────────────────────────────────────────────

    @abstractmethod
    def scrape(self) -> list[dict[str, Any]]:
        """
        Scrape the portal and return a list of raw job/notice dicts.

        Each dict should contain:
            title, organization, notification_url, pdf_url, source_name
        Optional: start_date, last_date, exam_date, pay_level_or_ctc, gate_required
        """

    def run(self) -> list[dict[str, Any]]:
        """
        Safe wrapper around scrape(). Returns empty list on any failure.
        One portal failing never crashes the pipeline.

        Deduplication:
          Results are filtered through the URL fingerprint store (dedup.py).
          Any notification_url or pdf_url already seen is silently skipped —
          no pdfplumber, no Gemini call, no DB write. The first 16 chars of
          the SHA-256 hash are logged for debugging.
        """
        from dedup import is_new_url, mark_url_seen

        try:
            raw_results = self.scrape()
        except Exception as exc:
            logger.error("[%s] Scraper crashed: %s", self.SOURCE_NAME, exc, exc_info=True)
            return []

        filtered = []
        skipped  = 0
        for result in (raw_results or []):
            # Use the most specific URL available as the dedup key
            dedup_url = result.get("pdf_url") or result.get("notification_url") or ""
            if not dedup_url:
                filtered.append(result)
                continue
            if is_new_url(dedup_url):
                filtered.append(result)
                mark_url_seen(dedup_url, source_name=self.SOURCE_NAME)
            else:
                skipped += 1

        if skipped:
            logger.info("[%s] Dedup skipped %d already-seen notice(s).", self.SOURCE_NAME, skipped)
        logger.info("[%s] Scraped %d new notice(s) (raw=%d).",
                    self.SOURCE_NAME, len(filtered), len(raw_results or []))
        return filtered


# ============================================================================
# ScraperRunner — Orchestrates multiple scrapers, supports threading
# ============================================================================

class ScraperRunner:
    """
    Runs a list of BaseScraper instances either:
      - Blocking (run_all_blocking)  — waits for all to finish; for testing.
      - Async    (run_all_async)     — fires daemon threads; web request returns immediately.
    """

    def __init__(
        self,
        on_result: Callable[[list[dict]], None] | None = None,
        on_complete: Callable[[int], None] | None = None,
    ):
        """
        Args:
            on_result:   Called after each scraper finishes with its results list.
            on_complete: Called once all scrapers finish with total notice count.
        """
        self.on_result   = on_result   or (lambda results: None)
        self.on_complete = on_complete or (lambda count: None)
        self._threads: list[Thread] = []

    def _run_scraper(self, scraper: BaseScraper, results_accumulator: list) -> None:
        """Target function for each thread."""
        results = scraper.run()
        results_accumulator.extend(results)
        try:
            self.on_result(results)
        except Exception as exc:
            logger.error("on_result callback error: %s", exc)

    def run_all_blocking(self, scrapers: list[BaseScraper]) -> list[dict]:
        """
        Run all scrapers sequentially (blocking). Used in tests and CLI.
        Returns combined list of all results.
        """
        all_results: list[dict] = []
        for scraper in scrapers:
            results = scraper.run()
            all_results.extend(results)
            try:
                self.on_result(results)
            except Exception as exc:
                logger.error("on_result callback error: %s", exc)
        try:
            self.on_complete(len(all_results))
        except Exception as exc:
            logger.error("on_complete callback error: %s", exc)
        return all_results

    def run_all_async(self, scrapers: list[BaseScraper]) -> None:
        """
        Fire all scrapers in daemon threads and return immediately.
        The web request (POST /fetch-now) returns a 202 Accepted without blocking.

        A final coordinator thread calls on_complete when all workers finish.
        """
        all_results: list[dict] = []
        done_event = Event()
        total_scrapers = len(scrapers)
        finished = [0]

        def worker(scraper: BaseScraper):
            self._run_scraper(scraper, all_results)
            finished[0] += 1
            if finished[0] == total_scrapers:
                done_event.set()
                try:
                    self.on_complete(len(all_results))
                except Exception as exc:
                    logger.error("on_complete callback error: %s", exc)

        self._threads = []
        for scraper in scrapers:
            t = Thread(target=worker, args=(scraper,), daemon=True, name=f"scraper-{scraper.SOURCE_NAME}")
            t.start()
            self._threads.append(t)

        logger.info("[ScraperRunner] Fired %d scraper threads (non-blocking).", len(scrapers))

    def wait(self, timeout: float = 120.0) -> None:
        """Block until all async threads complete. Used in tests only."""
        for t in self._threads:
            t.join(timeout=timeout)


# ============================================================================
# _BaseGovScraper — Shared logic for Indian gov portals
# ============================================================================

class _BaseGovScraper(BaseScraper):
    """
    Intermediate base with shared logic for Indian government career pages.
    Most portals have a recruitment page listing PDF links.
    """

    ORGANIZATION: str = ""   # e.g. "DRDO RAC", "NIELIT"

    def _build_job_dict(
        self,
        title: str = "",
        notification_url: str = "",
        pdf_url: str = "",
        extra: dict | None = None,
    ) -> dict[str, Any]:
        """Build a standardised raw job dict."""
        d = {
            "title":            title,
            "organization":     self.ORGANIZATION or self.SOURCE_NAME,
            "notification_url": notification_url,
            "pdf_url":          pdf_url,
            "source_name":      self.SOURCE_NAME,
        }
        if extra:
            d.update(extra)
        return d

    def _scrape_generic_career_page(
        self,
        page_url: str | None = None,
        extra_keywords: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Generic scraper for a portal with a recruitment listing page.
        Finds all recruitment-related links and associated PDF links.
        """
        page_url = page_url or self.SOURCE_URL
        soup = self.get_soup(page_url)
        if soup is None:
            return []

        jobs = []
        rec_links = self.find_recruitment_links(soup, page_url, extra_keywords)
        pdf_links  = self.find_pdf_links(soup, page_url)

        # Jobs with PDF links directly on the page
        for pdf_url in pdf_links:
            jobs.append(self._build_job_dict(
                title=Path(urllib.parse.urlparse(pdf_url).path).stem.replace("_", " "),
                notification_url=page_url,
                pdf_url=pdf_url,
            ))

        # Jobs from recruitment links (may link to a sub-page with PDF)
        for link in rec_links:
            # Skip if already captured as a PDF link
            if any(j["notification_url"] == link["url"] or j["pdf_url"] == link["url"] for j in jobs):
                continue
            jobs.append(self._build_job_dict(
                title=link["title"],
                notification_url=link["url"],
                pdf_url="",
            ))

        return jobs
