"""
blueprints/auth.py — Google OAuth2 web authorization flow for Calendar access.

Routes:
  - GET  /auth/google           Initiates OAuth2 redirect to Google consent screen
  - GET  /auth/google/callback  Handles Google redirect, writes token.json
  - GET  /auth/google/status    Returns JSON status of Google Calendar authorization
  - POST /auth/google/disconnect Removes saved token.json
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Blueprint, current_app, flash, jsonify, redirect, request, session, url_for

import calendar_sync

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


@auth_bp.route("/google", methods=["GET"])
def google_auth():
    """Initiate Google OAuth2 web authorization flow."""
    creds_path = Path(current_app.config.get("GOOGLE_CREDENTIALS_PATH", calendar_sync.CREDENTIALS_FILE))
    if not creds_path.exists():
        msg = (
            f"Google credentials file not found at '{creds_path.resolve()}'. "
            "Please download your credentials.json from Google Cloud Console "
            "and place it in the application root."
        )
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": msg}), 404
        flash(msg, "error")
        return redirect(url_for("settings.view_settings"))

    try:
        from google_auth_oauthlib.flow import Flow

        # Use HTTPS in production, allow HTTP in local dev
        if not current_app.debug:
            os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "0"
        else:
            os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

        redirect_uri = url_for("auth.google_callback", _external=True)
        flow = Flow.from_client_secrets_file(
            str(creds_path),
            scopes=_SCOPES,
            redirect_uri=redirect_uri,
        )

        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        session["oauth_state"] = state
        return redirect(auth_url)

    except Exception as exc:
        logger.error("Failed to initiate Google OAuth: %s", exc)
        msg = f"OAuth initialization error: {exc}"
        if request.is_json or request.headers.get("Accept") == "application/json":
            return jsonify({"status": "error", "message": msg}), 500
        flash(msg, "error")
        return redirect(url_for("settings.view_settings"))


@auth_bp.route("/google/callback", methods=["GET"])
def google_callback():
    """Handle OAuth2 callback from Google."""
    code = request.args.get("code")
    if not code:
        err = request.args.get("error", "Access denied by user.")
        flash(f"Google authorization failed: {err}", "error")
        return redirect(url_for("settings.view_settings"))

    creds_path = Path(current_app.config.get("GOOGLE_CREDENTIALS_PATH", calendar_sync.CREDENTIALS_FILE))
    token_path = Path(current_app.config.get("GOOGLE_TOKEN_PATH", calendar_sync.TOKEN_FILE))

    try:
        from google_auth_oauthlib.flow import Flow

        redirect_uri = url_for("auth.google_callback", _external=True)
        flow = Flow.from_client_secrets_file(
            str(creds_path),
            scopes=_SCOPES,
            redirect_uri=redirect_uri,
        )
        flow.fetch_token(code=code)
        creds = flow.credentials

        token_path.write_text(creds.to_json())
        flash("Google Calendar connected successfully! Deadlines will now sync to your calendar.", "success")
        logger.info("Google OAuth credentials saved to %s", token_path.resolve())

    except Exception as exc:
        logger.error("Failed to exchange OAuth token: %s", exc)
        flash(f"Failed to complete Google authorization: {exc}", "error")

    return redirect(url_for("settings.view_settings"))


@auth_bp.route("/google/status", methods=["GET"])
def google_status():
    """Check current Google Calendar authorization status."""
    is_connected = calendar_sync.is_calendar_configured()
    return jsonify({
        "is_connected": is_connected,
        "calendar_id": current_app.config.get("GOOGLE_CALENDAR_ID", "primary"),
    })


@auth_bp.route("/google/disconnect", methods=["POST"])
def google_disconnect():
    """Disconnect Google Calendar by deleting token.json."""
    token_path = Path(current_app.config.get("GOOGLE_TOKEN_PATH", calendar_sync.TOKEN_FILE))
    if token_path.exists():
        try:
            token_path.unlink()
            logger.info("Google token deleted: %s", token_path.resolve())
            msg = "Google Calendar disconnected."
            status = "success"
        except Exception as exc:
            logger.error("Failed to delete token file: %s", exc)
            msg = f"Error disconnecting: {exc}"
            status = "error"
    else:
        msg = "No Google Calendar connection found to disconnect."
        status = "info"

    if request.is_json or request.headers.get("Accept") == "application/json":
        return jsonify({"status": status, "message": msg})

    flash(msg, status)
    return redirect(url_for("settings.view_settings"))
