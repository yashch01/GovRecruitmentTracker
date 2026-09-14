"""
blueprints/settings.py — User preferences, profile, and integration settings.

Features:
  - User profile: Date of Birth and Social Category (General, OBC, SC, ST, EWS)
    for age-limit verification and relaxation calculations.
  - Telegram integration settings: Bot token, Chat ID, and instant connection tester.
  - Google Calendar connection status display and configuration.
  - Feature Flags management for toggling experimental / future features.
"""

from __future__ import annotations

import json
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import calendar_sync
from models import ReservationCategory, UserSettings, db
import telegram_notifier

logger = logging.getLogger(__name__)

settings_bp = Blueprint("settings", __name__)


def _get_or_create_settings() -> UserSettings:
    """Ensure a UserSettings row always exists and return it."""
    settings = UserSettings.query.first()
    if not settings:
        settings = UserSettings(
            date_of_birth=None,
            category=ReservationCategory.GENERAL,
            telegram_bot_token="",
            telegram_chat_id="",
            feature_flags=json.dumps({
                "dark_mode": True,
                "auto_calendar_sync": False,
                "telegram_instant_alert": True,
                "hide_expired_jobs": False,
            }),
        )
        db.session.add(settings)
        db.session.commit()
    return settings


@settings_bp.route("", methods=["GET"])
@settings_bp.route("/", methods=["GET"])
def view_settings():
    """Display user profile and integrations settings."""
    settings = _get_or_create_settings()
    is_calendar_connected = calendar_sync.is_calendar_configured()
    is_telegram_ready = telegram_notifier.is_telegram_configured(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )

    try:
        flags = json.loads(settings.feature_flags or "{}")
    except Exception:
        flags = {}

    if request.is_json or request.headers.get("Accept") == "application/json":
        return jsonify({
            "settings": settings.to_dict(),
            "calendar_connected": is_calendar_connected,
            "telegram_connected": is_telegram_ready,
            "feature_flags": flags,
            "reservation_categories": ReservationCategory.ALL,
        })

    return render_template(
        "settings.html",
        settings=settings,
        calendar_connected=is_calendar_connected,
        telegram_connected=is_telegram_ready,
        feature_flags=flags,
        categories=ReservationCategory.ALL,
    )


@settings_bp.route("", methods=["POST"])
@settings_bp.route("/", methods=["POST"])
def update_settings():
    """Update user profile, credentials, and feature flags."""
    settings = _get_or_create_settings()
    data = request.get_json(silent=True) or request.form.to_dict()

    # Date of Birth
    dob_str = data.get("date_of_birth", "").strip()
    if dob_str:
        parsed_dob = calendar_sync.parse_date(dob_str)
        if parsed_dob:
            settings.date_of_birth = parsed_dob
    elif "date_of_birth" in data and not dob_str:
        settings.date_of_birth = None

    # Category
    cat = data.get("category", "").strip()
    if cat in ReservationCategory.ALL:
        settings.category = cat

    # Telegram Credentials
    if "telegram_bot_token" in data:
        settings.telegram_bot_token = data.get("telegram_bot_token", "").strip()
    if "telegram_chat_id" in data:
        settings.telegram_chat_id = data.get("telegram_chat_id", "").strip()

    # Feature Flags
    if "feature_flags" in data:
        flags_input = data["feature_flags"]
        if isinstance(flags_input, dict):
            settings.feature_flags = json.dumps(flags_input)
        elif isinstance(flags_input, str):
            try:
                json.loads(flags_input)
                settings.feature_flags = flags_input
            except ValueError:
                pass
    else:
        # Check individual checkbox flags from HTML form
        try:
            current_flags = json.loads(settings.feature_flags or "{}")
        except Exception:
            current_flags = {}

        for key in ["auto_calendar_sync", "telegram_instant_alert", "hide_expired_jobs"]:
            if key in data:
                current_flags[key] = data[key] in ("true", "True", "1", "on", True)
        settings.feature_flags = json.dumps(current_flags)

    try:
        db.session.commit()
        msg = "Settings saved successfully."
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "success", "message": msg, "settings": settings.to_dict()})
        flash(msg, "success")
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to update settings: %s", exc)
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": str(exc)}), 500
        flash(f"Error saving settings: {exc}", "error")

    return redirect(url_for("settings.view_settings"))


@settings_bp.route("/test-telegram", methods=["POST"])
def test_telegram():
    """Send a verification test notification to Telegram."""
    settings = _get_or_create_settings()
    data = request.get_json(silent=True) or request.form.to_dict()

    bot_token = data.get("telegram_bot_token") or settings.telegram_bot_token
    chat_id = data.get("telegram_chat_id") or settings.telegram_chat_id

    ok, message = telegram_notifier.send_test_message(chat_id=chat_id, bot_token=bot_token)

    status_code = 200 if ok else 400
    if request.is_json or request.headers.get("Accept") == "application/json":
        return jsonify({"success": ok, "message": message}), status_code

    flash(message, "success" if ok else "error")
    return redirect(url_for("settings.view_settings"))
