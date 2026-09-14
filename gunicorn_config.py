"""
gunicorn_config.py — Production WSGI Server Configuration for GovRecruitmentTracker.

Optimized for cloud container environments (Render, Railway, Fly.io, Heroku):
  - Automatically binds to $PORT provided by container runtime (default 10000 on Render).
  - Threaded worker pool (gthread) for high I/O concurrency without memory bloat.
  - Request recycling to prevent memory leaks on free-tier 512MB RAM containers.
  - Generous timeouts (120s) and keepalive (5s) so Render's internal health-checker
    probes don't cause early worker recycling.
"""

from __future__ import annotations

import os

# ── Server Socket ─────────────────────────────────────────────────────────────
# Render and Heroku inject the $PORT environment variable (Render defaults to 10000)
port = os.getenv("PORT", "10000")
bind = f"0.0.0.0:{port}"

# ── Worker Processes & Concurrency ────────────────────────────────────────────
# On free tier (512MB RAM), 2 workers with 4 threads each gives optimal throughput
# without triggering out-of-memory (OOM) killer.
workers = int(os.getenv("WEB_CONCURRENCY", "2"))
threads = int(os.getenv("GUNICORN_THREADS", "4"))
worker_class = "gthread"

# ── Worker Lifetime & Memory Management ───────────────────────────────────────
# Restart workers periodically to reclaim memory from pdfplumber / BeautifulSoup
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "50"))

# ── Timeouts ──────────────────────────────────────────────────────────────────
# Generous timeout and keepalive so Render's internal health-checker probes don't cause early worker recycling
timeout = 120
keepalive = 5
graceful_timeout = 30

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog = "-"  # stdout
errorlog = "-"   # stderr
loglevel = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sµs'

# ── Process Naming ────────────────────────────────────────────────────────────
proc_name = "gov-recruitment-tracker"


def on_starting(server):
    """Log startup metadata."""
    server.log.info("Starting GovRecruitmentTracker on %s with %s worker(s), %s thread(s)", bind, workers, threads)


def post_fork(server, worker):
    """Log worker fork event."""
    server.log.info("Worker spawned (pid: %s)", worker.pid)
