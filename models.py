"""
models.py — SQLAlchemy ORM models for GovRecruitmentTracker.

Database URL priority:
  1. DATABASE_URL environment variable (Render / PythonAnywhere cloud)
  2. Fallback: SQLite file `recruitment_tracker.db` in the project root (local dev)
"""

import hashlib
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.ext.hybrid import hybrid_property

db = SQLAlchemy()


def _now_utc() -> datetime:
    """Return current UTC datetime. Used as SQLAlchemy default/onupdate callable."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enums (stored as plain strings for SQLite / portability)
# ---------------------------------------------------------------------------

class ExamCategory:
    TECHNICAL_CS_IT     = "Technical CS/IT"
    COMPETITIVE_EXAM    = "Competitive Exam"
    PSU                 = "PSU"
    MILITARY            = "Military"
    BANKING             = "Banking"
    OTHER               = "Other"

    ALL = [
        TECHNICAL_CS_IT,
        COMPETITIVE_EXAM,
        PSU,
        MILITARY,
        BANKING,
        OTHER,
    ]


class ApplicationStatus:
    DISCOVERED          = "Discovered"
    NOT_APPLIED         = "Not Applied"
    INTERESTED          = "Interested"
    APPLIED             = "Applied"
    ADMIT_CARD          = "Admit Card"
    ADMIT_CARD_OUT      = "Admit Card Out"
    EXAM_SCHEDULED      = "Exam Scheduled"
    EXAM_DONE           = "Exam Done"
    SELECTED            = "Selected"
    NEEDS_MANUAL_CHECK  = "Needs Manual Check"
    ARCHIVED            = "Archived"

    ALL = [
        DISCOVERED,
        NOT_APPLIED,
        INTERESTED,
        APPLIED,
        ADMIT_CARD,
        ADMIT_CARD_OUT,
        EXAM_SCHEDULED,
        EXAM_DONE,
        SELECTED,
        NEEDS_MANUAL_CHECK,
        ARCHIVED,
    ]


class UserCategory:
    GENERAL = "General"
    OBC     = "OBC"
    SC      = "SC"
    ST      = "ST"
    EWS     = "EWS"

    ALL = [GENERAL, OBC, SC, ST, EWS]


class SourceCategory:
    PSU         = "PSU"
    SSC         = "SSC"
    UPSC        = "UPSC"
    BANKING     = "Banking"
    MILITARY    = "Military"
    TECHNICAL   = "Technical"
    OTHER       = "Other"

    ALL = [PSU, SSC, UPSC, BANKING, MILITARY, TECHNICAL, OTHER]


# Backward/forward compatible aliases
UserStatus = ApplicationStatus
ReservationCategory = UserCategory
# ---------------------------------------------------------------------------

class Source(db.Model):  # type: ignore[name-defined]
    """Government recruitment portals / RSS feeds to be scraped."""

    __tablename__ = "sources"

    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(200), nullable=False)
    url             = db.Column(db.String(1000), nullable=False)
    source_category = db.Column(
        db.String(50),
        nullable=False,
        default=SourceCategory.OTHER
    )
    scraper_type    = db.Column(db.String(100), default="GenericCareerScraper")
    is_active       = db.Column(db.Boolean, nullable=False, default=True)
    notes           = db.Column(db.Text, default="")
    created_at      = db.Column(
        db.DateTime,
        nullable=False,
        default=_now_utc,
    )

    @hybrid_property
    def category(self):
        return self.source_category

    @category.setter  # type: ignore[no-redef]
    def category(self, val):
        self.source_category = val

    def __repr__(self):
        status = "✓" if self.is_active else "✗"
        return f"<Source [{status}] {self.name} | {self.source_category}>"

    def to_dict(self):
        return {
            "id":              self.id,
            "name":            self.name,
            "url":             self.url,
            "source_category": self.source_category,
            "category":        self.source_category,
            "scraper_type":    self.scraper_type or "GenericCareerScraper",
            "is_active":       self.is_active,
            "notes":           self.notes,
            "created_at":      self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# Table: jobs
# ---------------------------------------------------------------------------

class Job(db.Model):  # type: ignore[name-defined]
    """A single government recruitment / exam notification."""

    __tablename__ = "jobs"

    # ── Identity ─────────────────────────────────────────────────────────────
    id                  = db.Column(db.Integer, primary_key=True)
    title               = db.Column(db.String(500), nullable=False)
    organization        = db.Column(db.String(300), nullable=False)
    exam_category       = db.Column(
        db.String(50),
        nullable=False,
        default=ExamCategory.OTHER
    )

    # ── Pay / Compensation ────────────────────────────────────────────────────
    pay_level_or_ctc    = db.Column(db.String(300), default="")

    # ── Source Links ──────────────────────────────────────────────────────────
    notification_url    = db.Column(db.String(1000), default="")
    pdf_url             = db.Column(db.String(1000), default="")
    local_pdf_path      = db.Column(db.String(500), default="")   # path in /archives/

    # ── Classification Flags ──────────────────────────────────────────────────
    is_gov              = db.Column(db.Boolean, nullable=False, default=True)
    is_cs_it            = db.Column(db.Boolean, nullable=False, default=False)
    any_graduate_eligible = db.Column(db.Boolean, nullable=False, default=False)
    gate_required       = db.Column(db.Boolean, nullable=False, default=False)

    # ── Important Dates (stored as strings for flexibility across formats) ─────
    start_date          = db.Column(db.String(50), default="")
    last_date           = db.Column(db.String(50), default="")       # registration deadline
    fee_last_date       = db.Column(db.String(50), default="")
    exam_date           = db.Column(db.String(50), default="")

    # ── Eligibility Details ───────────────────────────────────────────────────
    educational_qualifications = db.Column(db.String(500), default="")
    age_limit_details   = db.Column(db.String(300), default="")
    selection_summary   = db.Column(db.String(500), default="")      # Exam/Interview/Neg-marking

    # ── Application Tracking (user-managed) ───────────────────────────────────
    application_status  = db.Column(
        db.String(50),
        nullable=False,
        default=ApplicationStatus.DISCOVERED
    )
    registration_number = db.Column(db.String(100), default="")
    roll_number         = db.Column(db.String(100), default="")
    notes               = db.Column(db.Text, default="")

    # ── Calendar Sync ─────────────────────────────────────────────────────────
    is_synced_to_calendar = db.Column(db.Boolean, nullable=False, default=False)
    calendar_event_id   = db.Column(db.String(200), default="")      # Google Calendar event ID

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at          = db.Column(
        db.DateTime,
        nullable=False,
        default=_now_utc,
    )
    updated_at          = db.Column(
        db.DateTime,
        nullable=False,
        default=_now_utc,
        onupdate=_now_utc,
    )

    @hybrid_property
    def user_status(self):
        return self.application_status

    @user_status.setter  # type: ignore[no-redef]
    def user_status(self, val):
        self.application_status = val

    @hybrid_property
    def eligible_cs_it(self):
        return self.is_cs_it

    @eligible_cs_it.setter  # type: ignore[no-redef]
    def eligible_cs_it(self, val):
        self.is_cs_it = val

    @hybrid_property
    def pdf_archive_path(self):
        return self.local_pdf_path

    @pdf_archive_path.setter  # type: ignore[no-redef]
    def pdf_archive_path(self, val):
        self.local_pdf_path = val

    def __repr__(self):
        return f"<Job #{self.id} | {self.organization} — {self.title[:60]}>"

    def to_dict(self):
        return {
            "id":                   self.id,
            "title":                self.title,
            "organization":         self.organization,
            "exam_category":        self.exam_category,
            "pay_level_or_ctc":     self.pay_level_or_ctc,
            "notification_url":     self.notification_url,
            "pdf_url":              self.pdf_url,
            "local_pdf_path":       self.local_pdf_path,
            "pdf_archive_path":     self.local_pdf_path,
            "is_gov":               self.is_gov,
            "is_cs_it":             self.is_cs_it,
            "eligible_cs_it":       self.is_cs_it,
            "any_graduate_eligible": self.any_graduate_eligible,
            "gate_required":        self.gate_required,
            "start_date":           self.start_date,
            "last_date":            self.last_date,
            "fee_last_date":        self.fee_last_date,
            "exam_date":            self.exam_date,
            "age_limit_details":    self.age_limit_details,
            "selection_summary":    self.selection_summary,
            "educational_qualifications": getattr(self, "_educational_qualifications", ""),
            "application_status":   self.application_status,
            "user_status":          self.application_status,
            "registration_number":  self.registration_number,
            "roll_number":          self.roll_number,
            "notes":                self.notes,
            "is_synced_to_calendar": self.is_synced_to_calendar,
            "calendar_event_id":    self.calendar_event_id,
            "created_at":           self.created_at.isoformat() if self.created_at else None,
            "updated_at":           self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Table: user_settings  (single-row; fetched as UserSettings.query.first())
# ---------------------------------------------------------------------------

class UserSettings(db.Model):  # type: ignore[name-defined]
    """User profile and app-wide settings. Designed as a single-row table."""

    __tablename__ = "user_settings"

    id                  = db.Column(db.Integer, primary_key=True)

    # ── Personal Profile ──────────────────────────────────────────────────────
    dob                 = db.Column(db.String(20), default="")        # ISO date string YYYY-MM-DD
    category            = db.Column(
        db.String(10),
        nullable=False,
        default=UserCategory.GENERAL
    )

    # ── Telegram Notifications (optional) ────────────────────────────────────
    telegram_bot_token  = db.Column(db.String(200), default="")
    telegram_chat_id    = db.Column(db.String(100), default="")

    # ── Feature Flags (JSON blob for future optional features) ────────────────
    # Example: '{"mock_test_tracker": false, "analytics": false}'
    feature_flags       = db.Column(db.Text, default="{}")

    # ── Timestamps ────────────────────────────────────────────────────────────
    updated_at          = db.Column(
        db.DateTime,
        nullable=False,
        default=_now_utc,
        onupdate=_now_utc,
    )

    @property
    def date_of_birth(self):
        if not self.dob:
            return None
        from calendar_sync import parse_date
        return parse_date(self.dob)

    @date_of_birth.setter
    def date_of_birth(self, val):
        if val is None:
            self.dob = ""
        elif isinstance(val, str):
            self.dob = val
        else:
            self.dob = val.isoformat()

    def __repr__(self):
        return f"<UserSettings DOB={self.dob} Category={self.category}>"

    def to_dict(self):
        return {
            "id":                   self.id,
            "dob":                  self.dob,
            "date_of_birth":        self.dob,
            "category":             self.category,
            "telegram_bot_token":   self.telegram_bot_token,
            "telegram_chat_id":     self.telegram_chat_id,
            "feature_flags":        self.feature_flags,
            "updated_at":           self.updated_at.isoformat() if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Table: seen_urls  (SHA-256 URL deduplication fingerprints)
# ---------------------------------------------------------------------------

class SeenURL(db.Model):  # type: ignore[name-defined]
    """
    Lightweight deduplication table.

    Before downloading/parsing any notification, compute sha256(url) and check
    this table. If the hash is already present, skip the notice entirely —
    no pdfplumber extraction, no Gemini API call, no DB write.

    After the first full sync run, subsequent daily syncs only process
    genuinely new notifications, protecting the free-tier Gemini quota.
    """

    __tablename__ = "seen_urls"

    id         = db.Column(db.Integer, primary_key=True)
    url_hash   = db.Column(db.String(64), nullable=False, unique=True, index=True)
    url        = db.Column(db.String(2000), nullable=False)
    source_name = db.Column(db.String(200), default="")
    first_seen = db.Column(
        db.DateTime,
        nullable=False,
        default=_now_utc,
    )

    def __repr__(self):
        return f"<SeenURL hash={self.url_hash[:12]}… seen={self.first_seen.date()}>"

    @classmethod
    def is_seen(cls, url: str) -> bool:
        """Return True if this URL has already been processed."""
        h = hashlib.sha256(url.encode()).hexdigest()
        return cls.query.filter_by(url_hash=h).first() is not None

    @classmethod
    def mark_seen(cls, url: str, source_name: str = "") -> "SeenURL":
        """
        Record a URL as processed. Idempotent — safe to call even if already seen.
        Returns the SeenURL row.
        """
        h = hashlib.sha256(url.encode()).hexdigest()
        existing = cls.query.filter_by(url_hash=h).first()
        if existing:
            return existing
        row = cls(url_hash=h, url=url[:2000], source_name=source_name)
        db.session.add(row)
        db.session.commit()
        return row


DEFAULT_SOURCES = [
    # ── Technical PSUs / Research Orgs ────────────────────────────────────────
    {
        "name": "NIELIT – National Institute of Electronics and IT",
        "url":  "https://www.nielit.gov.in/recruitment",
        "source_category": SourceCategory.TECHNICAL,
    },
    {
        "name": "CDAC – Centre for Development of Advanced Computing",
        "url":  "https://www.cdac.in/index.aspx?id=careers",
        "source_category": SourceCategory.TECHNICAL,
    },
    {
        "name": "NIC – National Informatics Centre (NCS IT Feed)",
        "url":  "https://www.nic.in/recruitment/",
        "source_category": SourceCategory.TECHNICAL,
    },
    {
        "name": "BIS – Bureau of Indian Standards",
        "url":  "https://www.bis.gov.in/index.php/about-bis/human-resource/recruitment/",
        "source_category": SourceCategory.PSU,
    },
    {
        "name": "DRDO RAC – Recruitment & Assessment Centre",
        "url":  "https://rac.gov.in/",
        "source_category": SourceCategory.TECHNICAL,
    },
    {
        "name": "BARC – Bhabha Atomic Research Centre",
        "url":  "https://recruit.barc.gov.in/barcrecruit/",
        "source_category": SourceCategory.TECHNICAL,
    },
    {
        "name": "BEL – Bharat Electronics Limited",
        "url":  "https://bel-india.in/careers/",
        "source_category": SourceCategory.PSU,
    },
    {
        "name": "ECIL – Electronics Corporation of India Limited",
        "url":  "https://www.ecil.co.in/jobs.html",
        "source_category": SourceCategory.PSU,
    },
    # ── Competitive Exams ─────────────────────────────────────────────────────
    {
        "name": "SSC – Staff Selection Commission",
        "url":  "https://ssc.gov.in/",
        "source_category": SourceCategory.SSC,
    },
    {
        "name": "UPSC – Union Public Service Commission",
        "url":  "https://www.upsc.gov.in/examinations/active-examinations",
        "source_category": SourceCategory.UPSC,
    },
    # ── Banking ───────────────────────────────────────────────────────────────
    {
        "name": "IBPS – Institute of Banking Personnel Selection",
        "url":  "https://www.ibps.in/",
        "source_category": SourceCategory.BANKING,
    },
    {
        "name": "SBI – State Bank of India Careers",
        "url":  "https://bank.sbi/careers",
        "source_category": SourceCategory.BANKING,
    },
    # ── Aggregator Feed ───────────────────────────────────────────────────────
    {
        "name": "FreeJobAlert – Central Govt IT / CS Jobs Feed",
        "url":  "https://www.freejobalert.com/government-jobs/",
        "source_category": SourceCategory.OTHER,
    },
]


def seed_default_sources():
    """Insert default government portals if the sources table is empty."""
    if Source.query.count() == 0:
        for data in DEFAULT_SOURCES:
            source = Source(
                name=data["name"],
                url=data["url"],
                source_category=data["source_category"],
                is_active=True,
            )
            db.session.add(source)

        # Create default single-row user settings
        if UserSettings.query.count() == 0:
            db.session.add(UserSettings(category=UserCategory.GENERAL))

        db.session.commit()
        print(f"✓ Seeded {len(DEFAULT_SOURCES)} default sources and user settings.")
    else:
        print("✓ Sources table already has data — skipping seed.")
