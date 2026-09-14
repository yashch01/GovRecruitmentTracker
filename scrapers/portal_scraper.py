"""
scrapers/portal_scraper.py — Concrete portal scrapers for GovRecruitmentTracker.

Each class extends _BaseGovScraper and knows how to extract recruitment notices
from a specific Indian government / banking / competitive exam portal.

Also provides:
  - GenericCareerScraper: for user-added portal URLs (dynamic SOURCE_URL).
  - SCRAPER_REGISTRY: maps source name → scraper class.
  - build_scrapers_for_sources(): builds active scraper list from DB Source rows.
  - run_scraper_pipeline(): high-level entry point used by Flask routes.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Type

from scrapers.base import (
    BaseScraper,
    ScraperRunner,
    _BaseGovScraper,
    resolve_url,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Technical PSU / Research Org Scrapers
# ============================================================================

class NIELITScraper(_BaseGovScraper):
    """NIELIT – National Institute of Electronics and Information Technology."""

    SOURCE_NAME  = "NIELIT"
    SOURCE_URL   = "https://www.nielit.gov.in/recruitment"
    ORGANIZATION = "NIELIT"

    def scrape(self) -> list[dict[str, Any]]:
        soup = self.get_soup(self.SOURCE_URL)
        if soup is None:
            return []

        jobs = []
        # NIELIT typically lists notices in <ul>/<li> or <table> with PDF links
        for a in soup.find_all("a", href=True):
            href  = a["href"].strip()
            text  = a.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            abs_url = resolve_url(self.SOURCE_URL, href)
            if re.search(r"recruit|vacanc|notif|advt|scientist|engineer|officer", text, re.I):
                pdf_url = abs_url if abs_url.lower().endswith(".pdf") else ""
                notif_url = "" if pdf_url else abs_url
                jobs.append(self._build_job_dict(
                    title=text[:200],
                    notification_url=notif_url or self.SOURCE_URL,
                    pdf_url=pdf_url,
                ))
        return jobs


class CDACscraper(_BaseGovScraper):
    """CDAC – Centre for Development of Advanced Computing."""

    SOURCE_NAME  = "CDAC"
    SOURCE_URL   = "https://www.cdac.in/index.aspx?id=careers"
    ORGANIZATION = "CDAC"

    def scrape(self) -> list[dict[str, Any]]:
        return self._scrape_generic_career_page(
            extra_keywords=["recruitment", "vacancy", "opening", "project", "scientist", "engineer"]
        )


class NICAPScraper(_BaseGovScraper):
    """NIC – National Informatics Centre Recruitment Page."""

    SOURCE_NAME  = "NIC"
    SOURCE_URL   = "https://www.nic.in/recruitment/"
    ORGANIZATION = "NIC"

    def scrape(self) -> list[dict[str, Any]]:
        return self._scrape_generic_career_page()


class BISScraper(_BaseGovScraper):
    """BIS – Bureau of Indian Standards."""

    SOURCE_NAME  = "BIS"
    SOURCE_URL   = "https://www.bis.gov.in/index.php/about-bis/human-resource/recruitment/"
    ORGANIZATION = "BIS"

    def scrape(self) -> list[dict[str, Any]]:
        return self._scrape_generic_career_page()


class DRDORACscraper(_BaseGovScraper):
    """DRDO RAC – Recruitment & Assessment Centre."""

    SOURCE_NAME  = "DRDO RAC"
    SOURCE_URL   = "https://rac.gov.in/"
    ORGANIZATION = "DRDO RAC"

    def scrape(self) -> list[dict[str, Any]]:
        soup = self.get_soup(self.SOURCE_URL)
        if soup is None:
            return []

        jobs = []
        # RAC lists advts as PDF links with advt numbers
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True)
            abs_url = resolve_url(self.SOURCE_URL, href)
            if re.search(r"advt|recruit|scientist|engineer|notif", text + href, re.I):
                pdf_url   = abs_url if abs_url.lower().endswith(".pdf") else ""
                notif_url = "" if pdf_url else abs_url
                jobs.append(self._build_job_dict(
                    title=text[:200] or "DRDO Recruitment Notice",
                    notification_url=notif_url or self.SOURCE_URL,
                    pdf_url=pdf_url,
                ))
        return jobs


class BARCScraper(_BaseGovScraper):
    """BARC – Bhabha Atomic Research Centre."""

    SOURCE_NAME  = "BARC"
    SOURCE_URL   = "https://www.barc.gov.in/recruit/"
    ORGANIZATION = "BARC"

    def scrape(self) -> list[dict[str, Any]]:
        return self._scrape_generic_career_page()


class BELScraper(_BaseGovScraper):
    """BEL – Bharat Electronics Limited."""

    SOURCE_NAME  = "BEL"
    SOURCE_URL   = "https://bel-india.in/Content.aspx?ContentId=2"
    ORGANIZATION = "BEL"

    def scrape(self) -> list[dict[str, Any]]:
        return self._scrape_generic_career_page(
            extra_keywords=["recruitment", "vacancy", "trainee", "engineer", "officer", "notification"]
        )


class ECILScraper(_BaseGovScraper):
    """ECIL – Electronics Corporation of India Limited."""

    SOURCE_NAME  = "ECIL"
    SOURCE_URL   = "https://www.ecil.co.in/careers/"
    ORGANIZATION = "ECIL"

    def scrape(self) -> list[dict[str, Any]]:
        return self._scrape_generic_career_page()


# ============================================================================
# Competitive Exam Scrapers
# ============================================================================

class SSCScraper(_BaseGovScraper):
    """SSC – Staff Selection Commission."""

    SOURCE_NAME  = "SSC"
    SOURCE_URL   = "https://ssc.gov.in/"
    ORGANIZATION = "Staff Selection Commission"

    _NOTICE_PAGE = "https://ssc.gov.in/Portal/Notices"

    def scrape(self) -> list[dict[str, Any]]:
        # Try the notices page first, fall back to home
        soup = self.get_soup(self._NOTICE_PAGE) or self.get_soup(self.SOURCE_URL)
        if soup is None:
            return []

        jobs = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            abs_url = resolve_url(self.SOURCE_URL, href)
            # SSC announces CGL, CHSL, MTS, CPO, JE, Selection Posts
            if re.search(r"cgl|chsl|mts|cpo|je\b|selection\s+post|exam\s+notice|recruitment|vacancy", text + href, re.I):
                pdf_url   = abs_url if abs_url.lower().endswith(".pdf") else ""
                notif_url = "" if pdf_url else abs_url
                jobs.append(self._build_job_dict(
                    title=text[:200],
                    notification_url=notif_url or self._NOTICE_PAGE,
                    pdf_url=pdf_url,
                    extra={"exam_category": "Competitive Exam"},
                ))
        return jobs


class UPSCScraper(_BaseGovScraper):
    """UPSC – Union Public Service Commission."""

    SOURCE_NAME  = "UPSC"
    SOURCE_URL   = "https://www.upsc.gov.in/examinations/active-examinations"
    ORGANIZATION = "Union Public Service Commission"

    def scrape(self) -> list[dict[str, Any]]:
        soup = self.get_soup(self.SOURCE_URL)
        if soup is None:
            return []

        jobs = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            abs_url = resolve_url(self.SOURCE_URL, href)
            if re.search(r"exam|recruit|notif|advt|civil\s+serv|engineer|scientist", text + href, re.I):
                pdf_url   = abs_url if abs_url.lower().endswith(".pdf") else ""
                notif_url = "" if pdf_url else abs_url
                jobs.append(self._build_job_dict(
                    title=text[:200],
                    notification_url=notif_url or self.SOURCE_URL,
                    pdf_url=pdf_url,
                    extra={"exam_category": "Competitive Exam"},
                ))
        return jobs


# ============================================================================
# Banking Scrapers
# ============================================================================

class IBPSScraper(_BaseGovScraper):
    """IBPS – Institute of Banking Personnel Selection."""

    SOURCE_NAME  = "IBPS"
    SOURCE_URL   = "https://www.ibps.in/"
    ORGANIZATION = "IBPS"

    def scrape(self) -> list[dict[str, Any]]:
        soup = self.get_soup(self.SOURCE_URL)
        if soup is None:
            return []

        jobs = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            abs_url = resolve_url(self.SOURCE_URL, href)
            if re.search(r"po\b|clerk|so\b|rrb|crp|probationary|officer|specialist|notif|recruit", text + href, re.I):
                pdf_url   = abs_url if abs_url.lower().endswith(".pdf") else ""
                notif_url = "" if pdf_url else abs_url
                jobs.append(self._build_job_dict(
                    title=text[:200],
                    notification_url=notif_url or self.SOURCE_URL,
                    pdf_url=pdf_url,
                    extra={"exam_category": "Banking"},
                ))
        return jobs


class SBIScraper(_BaseGovScraper):
    """SBI – State Bank of India Careers."""

    SOURCE_NAME  = "SBI"
    SOURCE_URL   = "https://bank.sbi/careers"
    ORGANIZATION = "State Bank of India"

    def scrape(self) -> list[dict[str, Any]]:
        soup = self.get_soup(self.SOURCE_URL)
        if soup is None:
            return []

        jobs = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            abs_url = resolve_url(self.SOURCE_URL, href)
            if re.search(r"po\b|clerk|so\b|probationary|specialist|officer|notif|recruit|vacancy", text + href, re.I):
                pdf_url   = abs_url if abs_url.lower().endswith(".pdf") else ""
                notif_url = "" if pdf_url else abs_url
                jobs.append(self._build_job_dict(
                    title=text[:200],
                    notification_url=notif_url or self.SOURCE_URL,
                    pdf_url=pdf_url,
                    extra={"exam_category": "Banking"},
                ))
        return jobs


# ============================================================================
# Aggregator Scraper
# ============================================================================

class FreeJobAlertScraper(_BaseGovScraper):
    """FreeJobAlert – Central Government IT/CS Jobs feed."""

    SOURCE_NAME  = "FreeJobAlert"
    SOURCE_URL   = "https://www.freejobalert.com/central-government-jobs/"
    ORGANIZATION = "Various (Central Govt)"

    def scrape(self) -> list[dict[str, Any]]:
        soup = self.get_soup(self.SOURCE_URL)
        if soup is None:
            return []

        jobs = []
        # FreeJobAlert uses article/post listing format
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True)
            if not text or len(text) < 10:
                continue
            if re.search(
                r"computer|software|it\b|information\s+tech|scientist|engineer|"
                r"programmer|developer|analyst|ssc|upsc|drdo|barc|nielit|nic\b",
                text + href, re.I
            ):
                abs_url = resolve_url(self.SOURCE_URL, href)
                jobs.append(self._build_job_dict(
                    title=text[:200],
                    notification_url=abs_url,
                    pdf_url="",
                ))
        return jobs


# ============================================================================
# Generic Scraper — for user-added portal URLs
# ============================================================================

class GenericCareerScraper(_BaseGovScraper):
    """
    Generic career page scraper for user-added portals.
    Attempts to find recruitment notices via heuristic link analysis.
    Instantiate with source_name and source_url from the DB Source row.
    """

    def __init__(self, source_name: str, source_url: str, organization: str = "", **kwargs):
        self.SOURCE_NAME  = source_name
        self.SOURCE_URL   = source_url
        self.ORGANIZATION = organization or source_name
        super().__init__(**kwargs)

    def scrape(self) -> list[dict[str, Any]]:
        return self._scrape_generic_career_page()


# ============================================================================
# SCRAPER_REGISTRY — maps source name → scraper class
# ============================================================================

SCRAPER_REGISTRY: dict[str, Type[BaseScraper]] = {
    "NIELIT":                           NIELITScraper,
    "CDAC":                             CDACscraper,
    "NIC":                              NICAPScraper,
    "BIS":                              BISScraper,
    "DRDO RAC":                         DRDORACscraper,
    "BARC":                             BARCScraper,
    "BEL":                              BELScraper,
    "ECIL":                             ECILScraper,
    "SSC":                              SSCScraper,
    "UPSC":                             UPSCScraper,
    "IBPS":                             IBPSScraper,
    "SBI":                              SBIScraper,
    "FreeJobAlert":                     FreeJobAlertScraper,
    # Future scrapers slot in here
}


def build_scrapers_for_sources(
    sources: list,
    archives_dir: str = "archives",
) -> list[BaseScraper]:
    """
    Build a list of scraper instances from SQLAlchemy Source ORM rows.

    Sources with a known name in SCRAPER_REGISTRY get the specialist scraper.
    All others get GenericCareerScraper.

    Only active sources (source.is_active == True) are included.
    """
    scrapers = []
    for source in sources:
        if not getattr(source, "is_active", True):
            continue
        # Strip org prefix from name for registry lookup
        name = source.name.split("–")[0].strip()   # e.g. "NIELIT – National..." → "NIELIT"
        name = name.split("-")[0].strip()
        name = name.split("(")[0].strip()

        scraper_cls = SCRAPER_REGISTRY.get(name)
        if scraper_cls:
            inst = scraper_cls(archives_dir=archives_dir)
        else:
            inst = GenericCareerScraper(
                source_name=source.name,
                source_url=source.url,
                organization=source.name,
                archives_dir=archives_dir,
            )
        scrapers.append(inst)
    return scrapers


# ============================================================================
# run_scraper_pipeline — High-level entry point for Flask routes
# ============================================================================

def run_scraper_pipeline(
    sources: list,
    on_result: "Callable[[list[dict]], None] | None" = None,
    on_complete: "Callable[[int], None] | None" = None,
    blocking: bool = False,
    archives_dir: str = "archives",
) -> ScraperRunner:
    """
    Build scrapers from DB source rows and run them.

    Args:
        sources:     List of Source ORM objects (active sources only).
        on_result:   Callback called per scraper with its results list.
        on_complete: Callback called once when all scrapers finish.
        blocking:    If True, blocks until complete (for CLI/tests).
                     If False (default), fires daemon threads and returns immediately.
        archives_dir: Path to PDF archive directory.

    Returns the ScraperRunner (useful for .wait() in tests).
    """
    scrapers = build_scrapers_for_sources(sources, archives_dir=archives_dir)
    runner   = ScraperRunner(on_result=on_result, on_complete=on_complete)

    if blocking:
        runner.run_all_blocking(scrapers)
    else:
        runner.run_all_async(scrapers)

    return runner
