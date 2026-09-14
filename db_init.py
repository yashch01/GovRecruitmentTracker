"""
db_init.py — Initialize the database and seed default data.

Flask-SQLAlchemy stores SQLite databases in the `instance/` folder by default.
This script uses the full Flask app context to ensure paths are consistent.

Run once on first deploy:
    .venv/bin/python db_init.py

Safe to re-run: existing data is never overwritten.
"""

import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
# Render provides postgres:// but SQLAlchemy 2.x needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    print("[db_init] No DATABASE_URL set — using SQLite (instance/recruitment_tracker.db)")
else:
    print(f"[db_init] Using DATABASE_URL: {DATABASE_URL[:40]}…")

from flask import Flask
from models import db, seed_default_sources


def migrate_database():
    """Safely add new columns to existing tables if needed."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)

    # sources table migrations
    if "sources" in inspector.get_table_names():
        source_cols = [c["name"] for c in inspector.get_columns("sources")]
        if "scraper_type" not in source_cols:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE sources ADD COLUMN scraper_type VARCHAR(100) DEFAULT 'GenericCareerScraper'"))
                conn.commit()
                print("  ✓ Migrated: added sources.scraper_type column")

    # jobs table migrations
    if "jobs" in inspector.get_table_names():
        job_cols = [c["name"] for c in inspector.get_columns("jobs")]
        if "educational_qualifications" not in job_cols:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN educational_qualifications VARCHAR(500) DEFAULT ''"))
                conn.commit()
                print("  ✓ Migrated: added jobs.educational_qualifications column")


def init_database(flask_app=None):
    """Entry point for initializing database, migrating schema, and seeding defaults."""
    app_to_use = flask_app or app
    with app_to_use.app_context():
        db.create_all()
        migrate_database()
        print("✓ All tables created and migrated.")
        seed_default_sources()


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"]       = DATABASE_URL or "sqlite:///recruitment_tracker.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

if __name__ == "__main__":
    init_database(app)
    print("\n✓ Database initialisation complete.")
    print("  Run the app:  .venv/bin/flask --app app run")
