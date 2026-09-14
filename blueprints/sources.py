"""
blueprints/sources.py — Portal source manager for GovRecruitmentTracker.

Features:
  - List all configured government job portals with status & last scraped timestamps
  - Add new government portals (auto-assigned GenericCareerScraper or matched scraper)
  - Toggle portals active/inactive in real time
  - Delete user-added or obsolete portals
  - Manually trigger a scrape for an individual portal
"""

from __future__ import annotations

import logging
import threading
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for

from models import ExamCategory, Source, db

logger = logging.getLogger(__name__)

sources_bp = Blueprint("sources", __name__)


def _detect_scraper_type(url: str) -> str:
    """Auto-detect if a known portal scraper matches the URL; otherwise use GenericCareerScraper."""
    try:
        from scrapers.portal_scraper import SCRAPER_REGISTRY
        domain = urlparse(url).netloc.lower()
        for name, cls in SCRAPER_REGISTRY.items():
            base = getattr(cls, "BASE_URL", "")
            if base and urlparse(base).netloc.lower() in domain:
                return name
    except Exception as exc:
        logger.debug("Scraper registry lookup failed: %s", exc)
    return "GenericCareerScraper"


@sources_bp.route("", methods=["GET"])
@sources_bp.route("/", methods=["GET"])
def list_sources():
    """List all portal sources."""
    sources = Source.query.order_by(Source.name.asc()).all()

    if request.is_json or request.headers.get("Accept") == "application/json":
        return jsonify({
            "sources": [s.to_dict() for s in sources],
            "total": len(sources),
            "active_count": sum(1 for s in sources if s.is_active),
        })

    return render_template(
        "sources.html",
        sources=sources,
        categories=ExamCategory.ALL,
    )


@sources_bp.route("", methods=["POST"])
@sources_bp.route("/", methods=["POST"])
def add_source():
    """Add a new government recruitment portal."""
    data = request.get_json(silent=True) or request.form.to_dict()

    name = data.get("name", "").strip()
    url = data.get("url", "").strip()
    category = data.get("category", ExamCategory.OTHER).strip()

    if not name or not url:
        msg = "Both portal name and URL are required."
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": msg}), 400
        flash(msg, "error")
        return redirect(url_for("sources.list_sources"))

    if not (url.startswith("http://") or url.startswith("https://")):
        msg = "URL must begin with http:// or https://"
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": msg}), 400
        flash(msg, "error")
        return redirect(url_for("sources.list_sources"))

    # Deduplication check: check if source with this URL already exists
    existing = Source.query.filter_by(url=url).first()
    if existing:
        msg = f"A source with URL '{url}' already exists ({existing.name})."
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": msg}), 409
        flash(msg, "warning")
        return redirect(url_for("sources.list_sources"))

    scraper_type = data.get("scraper_type") or _detect_scraper_type(url)

    new_source = Source(
        name=name,
        url=url,
        category=category if category in ExamCategory.ALL else ExamCategory.OTHER,
        scraper_type=scraper_type,
        is_active=True,
    )

    try:
        db.session.add(new_source)
        db.session.commit()
        msg = f"Portal '{name}' added successfully."
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "success", "message": msg, "source": new_source.to_dict()}), 201
        flash(msg, "success")
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to add source: %s", exc)
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": str(exc)}), 500
        flash(f"Error adding source: {exc}", "error")

    return redirect(url_for("sources.list_sources"))


@sources_bp.route("/<int:source_id>/toggle", methods=["POST"])
def toggle_source(source_id: int):
    """Toggle a portal source active or inactive."""
    source = Source.query.get_or_404(source_id)
    source.is_active = not source.is_active

    try:
        db.session.commit()
        state = "activated" if source.is_active else "deactivated"
        msg = f"Portal '{source.name}' {state}."
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "success", "message": msg, "is_active": source.is_active})
        flash(msg, "info")
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to toggle source #%d: %s", source_id, exc)
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": str(exc)}), 500
        flash("Failed to update source state", "error")

    return redirect(request.referrer or url_for("sources.list_sources"))


@sources_bp.route("/<int:source_id>/delete", methods=["POST"])
def delete_source(source_id: int):
    """Delete a portal source."""
    source = Source.query.get_or_404(source_id)
    name = source.name

    try:
        db.session.delete(source)
        db.session.commit()
        msg = f"Portal '{name}' deleted."
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "success", "message": msg})
        flash(msg, "success")
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to delete source #%d: %s", source_id, exc)
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": str(exc)}), 500
        flash(f"Failed to delete source: {exc}", "error")

    return redirect(request.referrer or url_for("sources.list_sources"))


@sources_bp.route("/<int:source_id>/scrape-now", methods=["POST"])
def scrape_source_now(source_id: int):
    """Trigger an immediate scrape for an individual portal."""
    source = Source.query.get_or_404(source_id)

    app = current_app._get_current_object()  # type: ignore[attr-defined]

    def _scrape_single():
        with app.app_context():
            try:
                from scrapers.portal_scraper import build_scrapers_for_sources
                scrapers = build_scrapers_for_sources([source])
                if scrapers:
                    scrapers[0].run()
                    logger.info("Single scrape finished for %s", source.name)
            except Exception as exc:
                logger.error("Error in single source scrape #%d: %s", source_id, exc)

    thread = threading.Thread(target=_scrape_single, daemon=True, name=f"scrape-src-{source_id}")
    thread.start()

    msg = f"Scrape initiated for '{source.name}' in the background."
    if request.is_json or request.headers.get("Accept") == "application/json":
        return jsonify({"status": "started", "message": msg}), 202

    flash(msg, "info")
    return redirect(request.referrer or url_for("sources.list_sources"))


@sources_bp.route("/reset-cache", methods=["POST"])
def reset_cache():
    """
    Wipe orphaned SeenURL entries (or all SeenURL cache) so fresh scraper runs can re-extract.
    Query param ?all=1 or JSON {"all": true} wipes the entire cache.
    Default cleans orphaned entries (hashes not matching any active Job).
    """
    wipe_all = request.args.get("all", "").lower() in ("1", "true", "yes")
    data = request.get_json(silent=True) or {}
    if data.get("all"):
        wipe_all = True

    try:
        from db_init import clean_orphaned_seen_urls
        cleaned = clean_orphaned_seen_urls(wipe_all=wipe_all)
        mode_str = "all" if wipe_all else "orphaned"
        msg = f"Deduplication cache reset: {cleaned} {mode_str} entries removed. Scrapers can now re-extract."
        logger.info(msg)
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "success", "message": msg, "removed_count": cleaned, "mode": mode_str}), 200
        flash(msg, "success")
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to reset dedup cache: %s", exc)
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": str(exc)}), 500
        flash(f"Failed to reset dedup cache: {exc}", "error")

    return redirect(request.referrer or url_for("sources.list_sources"))

