"""
dedup.py — URL fingerprint deduplication for GovRecruitmentTracker.

Provides two access patterns:

  1. Flask app context (production):
     Uses SeenURL SQLAlchemy model — persisted across restarts.

  2. In-memory fallback (testing / no DB context):
     Uses a module-level set of hashes — lives for the process lifetime.
     Automatically activated when no Flask app context is available.

Usage in scrapers:
    from dedup import is_new_url, mark_url_seen

    if not is_new_url(notification_url):
        continue   # skip — already processed in a previous sync run

    # ... download, parse, save to DB ...
    mark_url_seen(notification_url, source_name="NIELIT")
"""

from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

# ─── In-memory fallback store ─────────────────────────────────────────────────
# Used when no Flask app context exists (e.g., standalone scripts, tests).
_memory_seen: set[str] = set()


def _compute_hash(url: str) -> str:
    """Return SHA-256 hex digest of the URL string."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def is_new_url(url: str) -> bool:
    """
    Return True if this URL has NOT been processed before — safe to proceed.
    Return False if already seen — skip to avoid re-parsing.

    Tries DB first; falls back to in-memory store if no app context.
    """
    if not url or not url.strip():
        return False

    h = _compute_hash(url)

    # Try Flask/DB path
    try:
        from flask import has_app_context
        if has_app_context():
            from models import SeenURL
            return not SeenURL.query.filter_by(url_hash=h).first()
    except Exception as exc:
        logger.warning("dedup DB check failed (%s) — using in-memory fallback.", exc)

    return h not in _memory_seen


def mark_url_seen(url: str, source_name: str = "") -> None:
    """
    Mark a URL as processed.

    Idempotent — calling twice on the same URL is safe.
    Writes to DB if app context available; in-memory store otherwise.
    """
    if not url or not url.strip():
        return

    h = _compute_hash(url)

    # Try Flask/DB path
    try:
        from flask import has_app_context
        if has_app_context():
            from models import SeenURL, db
            if not SeenURL.query.filter_by(url_hash=h).first():
                db.session.add(SeenURL(
                    url_hash=h,
                    url=url[:2000],
                    source_name=source_name,
                ))
                db.session.commit()
            return
    except Exception as exc:
        logger.warning("dedup DB write failed (%s) — falling back to in-memory.", exc)

    _memory_seen.add(h)


def clear_memory_store() -> None:
    """Clear the in-memory dedup store. Used in tests between runs."""
    _memory_seen.clear()


def memory_store_size() -> int:
    """Return number of URLs tracked in the in-memory store."""
    return len(_memory_seen)


def url_fingerprint(url: str) -> str:
    """Return the SHA-256 hex fingerprint for a URL (for external inspection/debugging)."""
    return _compute_hash(url)
