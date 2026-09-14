"""
config.py — Centralised Flask configuration.

Priority for DATABASE_URL:
  1. DATABASE_URL environment variable (cloud deploy)
  2. SQLite fallback (local dev)
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
    CRON_TOKEN = os.environ.get("CRON_TOKEN", "")

    # ── Database ──────────────────────────────────────────────────────────────
    _db_url = os.environ.get("DATABASE_URL", "").strip()
    # Render provides postgres:// but SQLAlchemy 2.x needs postgresql://
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url or "sqlite:///recruitment_tracker.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── Archives directory ────────────────────────────────────────────────────
    ARCHIVES_DIR = os.path.join(os.path.dirname(__file__), "archives")

    # ── Google APIs ───────────────────────────────────────────────────────────
    GEMINI_API_KEY              = os.environ.get("GEMINI_API_KEY", "")
    GOOGLE_CREDENTIALS_PATH     = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    GOOGLE_TOKEN_PATH           = os.environ.get("GOOGLE_TOKEN_PATH", "token.json")
    GOOGLE_CALENDAR_ID          = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

    # ── Telegram ─────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN          = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID            = os.environ.get("TELEGRAM_CHAT_ID", "")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


# Active config — override with FLASK_ENV=production
config_map = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
}

active_config = config_map.get(
    os.environ.get("FLASK_ENV", "development"),
    DevelopmentConfig,
)
