"""
db_init.py — Initialize the database and seed default data.

Flask-SQLAlchemy stores SQLite databases in the `instance/` folder by default.
This script uses the full Flask app context to ensure paths are consistent.

Run once on first deploy:
    .venv/bin/python db_init.py

Maintenance commands:
    .venv/bin/python db_init.py --reset-cache   # Clean orphaned SeenURL records
    .venv/bin/python db_init.py --wipe-cache    # Wipe all SeenURL records

Safe to re-run: existing data is never overwritten.
"""

import os
import sys
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

# Map legacy 404 recruitment portal URLs to new active portals
URL_MIGRATIONS = {
    "https://www.barc.gov.in/recruit/": "https://recruit.barc.gov.in/barcrecruit/",
    "https://bel-india.in/Content.aspx?ContentId=2": "https://bel-india.in/careers/",
    "https://www.ecil.co.in/careers/": "https://www.ecil.co.in/jobs.html",
    "https://www.freejobalert.com/central-government-jobs/": "https://www.freejobalert.com/government-jobs/",
}


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
        if "source_id" not in job_cols:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN source_id INTEGER REFERENCES sources(id)"))
                conn.commit()
                print("  ✓ Migrated: added jobs.source_id column")


def update_legacy_portal_urls() -> int:
    """Update legacy 404 portal URLs in the database to active URLs."""
    from models import Source
    updated = 0
    for old_url, new_url in URL_MIGRATIONS.items():
        src = Source.query.filter_by(url=old_url).first()
        if src:
            src.url = new_url
            updated += 1
            print(f"  ✓ Migrated portal URL for '{src.name}': {old_url} -> {new_url}")
    if updated > 0:
        db.session.commit()
    return updated


def clean_orphaned_seen_urls(wipe_all: bool = False) -> int:
    """
    Clean up SeenURL records that have no corresponding Job record in the database.
    If wipe_all is True, removes all records from SeenURL so scrapers re-extract everything.
    """
    from models import SeenURL, Job
    from dedup import clear_memory_store, url_fingerprint

    clear_memory_store()

    if wipe_all:
        count = SeenURL.query.count()
        SeenURL.query.delete()
        db.session.commit()
        print(f"  ✓ Wiped all {count} SeenURL records from dedup store.")
        return count

    # Collect active Job notification and PDF URL fingerprints
    active_hashes = set()
    for row in db.session.query(Job.notification_url, Job.pdf_url).all():
        if row[0]:
            active_hashes.add(url_fingerprint(row[0].strip()))
        if row[1]:
            active_hashes.add(url_fingerprint(row[1].strip()))

    all_seen = SeenURL.query.all()
    orphaned_count = 0
    for seen in all_seen:
        if seen.url_hash not in active_hashes:
            db.session.delete(seen)
            orphaned_count += 1

    if orphaned_count > 0:
        db.session.commit()
        print(f"  ✓ Cleaned {orphaned_count} orphaned SeenURL records (no corresponding Job notice).")
    else:
        print("  ✓ No orphaned SeenURL entries found.")

    return orphaned_count


def init_database(flask_app=None):
    """Entry point for initializing database, migrating schema, and seeding defaults."""
    app_to_use = flask_app or app
    with app_to_use.app_context():
        db.create_all()
        migrate_database()
        update_legacy_portal_urls()
        clean_orphaned_seen_urls()
        print("✓ All tables created and migrated.")
        seed_default_sources()


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"]       = DATABASE_URL or "sqlite:///recruitment_tracker.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

if __name__ == "__main__":
    with app.app_context():
        if "--wipe-cache" in sys.argv:
            count = clean_orphaned_seen_urls(wipe_all=True)
            print(f"Done. Wiped {count} records.")
        elif "--reset-cache" in sys.argv:
            count = clean_orphaned_seen_urls(wipe_all=False)
            print(f"Done. Cleaned {count} orphaned records.")
        else:
            init_database(app)
            print("\n✓ Database initialisation complete.")
            print("  Run the app:  .venv/bin/flask --app app run")
