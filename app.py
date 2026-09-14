"""
app.py — Main application factory and WSGI entry point for GovRecruitmentTracker.

Architecture:
  - Application factory pattern via create_app()
  - Centralized configuration with DATABASE_URL override support
  - SQLAlchemy ORM database initialization
  - Modular Blueprint registration:
      • dashboard_bp  (/)
      • jobs_bp       (/jobs, /fetch-now, /sync-calendar)
      • sources_bp    (/sources)
      • settings_bp   (/settings)
      • auth_bp       (/auth)
      • api_bp        (/api)
  - PDF archive streaming endpoint (/archives/<filename>)
  - Error handlers and CLI commands
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from config import active_config
from models import db

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app(config_object=None) -> Flask:
    """
    Flask application factory.

    Args:
        config_object: Configuration class or dict. If None, uses active_config.

    Returns:
        Flask: Configured Flask application instance.
    """
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # ── Load Configuration ───────────────────────────────────────────────────
    if config_object is None:
        app.config.from_object(active_config)
    elif isinstance(config_object, dict):
        app.config.from_mapping(config_object)
    else:
        app.config.from_object(config_object)

    # Ensure archives directory exists
    archives_dir = Path(app.config.get("ARCHIVES_DIR", os.path.join(app.root_path, "archives")))
    archives_dir.mkdir(parents=True, exist_ok=True)
    app.config["ARCHIVES_DIR"] = str(archives_dir)

    # ── Initialize Extensions ────────────────────────────────────────────────
    db.init_app(app)

    # ── Register Blueprints ──────────────────────────────────────────────────
    from blueprints.dashboard import dashboard_bp
    from blueprints.jobs import jobs_bp
    from blueprints.sources import sources_bp
    from blueprints.settings import settings_bp
    from blueprints.auth import auth_bp
    from blueprints.api import api_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(sources_bp, url_prefix="/sources")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(api_bp, url_prefix="/api")

    # ── Static Archive PDF Streaming ─────────────────────────────────────────
    @app.route("/archives/<path:filename>")
    def download_archive(filename: str):
        """Stream or download an archived recruitment notice PDF."""
        return send_from_directory(
            app.config["ARCHIVES_DIR"],
            filename,
            as_attachment=False,
            mimetype="application/pdf",
        )

    # ── Error Handlers ───────────────────────────────────────────────────────
    @app.errorhandler(404)
    def handle_not_found(err):
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"status": "error", "message": "Resource not found"}), 404
        return render_template("layout.html"), 404

    @app.errorhandler(500)
    def handle_server_error(err):
        logger.error("Internal server error: %s", err)
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"status": "error", "message": "Internal server error"}), 500
        return render_template("layout.html"), 500

    # ── CLI Commands ─────────────────────────────────────────────────────────
    @app.cli.command("init-db")
    def init_db_command():
        """Initialize database schema and seed default recruitment sources."""
        from db_init import init_database
        init_database(app)
        print("Database initialized and seeded.")

    return app


# WSGI entry point for gunicorn (e.g. gunicorn app:app)
app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", False))
