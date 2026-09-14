"""
telegram_notifier.py — Non-blocking Telegram notification dispatcher.

Sends recruitment alerts to a specified Telegram chat / channel using the
official Telegram Bot API.

Key Features:
  - Non-blocking: By default (async_send=True), launches a background daemon
    thread so scraping runs and web requests return immediately.
  - Zero-cost: Uses direct HTTP calls via `requests` without requiring
    heavy third-party Telegram bot SDKs.
  - Graceful Fallback: If TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are not
    configured, logs a debug message and skips silently without raising errors.
  - Robust HTML formatting: Escapes dynamic user text with html.escape so
    special characters never trigger Telegram 400 Bad Request errors.
  - Credential discovery: Checks explicit parameters -> Flask UserSettings
    ORM row -> Environment variables / Config.
"""

from __future__ import annotations

import html
import logging
import os
import threading
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Base URL for Telegram Bot API
_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"


def get_telegram_credentials(
    bot_token: str | None = None,
    chat_id: str | None = None,
) -> tuple[str, str]:
    """
    Resolve Telegram Bot Token and Chat ID from multiple sources in priority order:
      1. Explicit arguments passed to this function.
      2. UserSettings table in the active Flask application database (if available).
      3. Environment variables (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID).
      4. Config class attributes.

    Returns:
        tuple[str, str]: (bot_token, chat_id). Empty strings if unconfigured.
    """
    token = (bot_token or "").strip()
    chat = (chat_id or "").strip()

    # If both already provided, return immediately
    if token and chat:
        return token, chat

    # Check database UserSettings if within Flask app context
    try:
        from flask import current_app
        if current_app:
            from models import UserSettings
            settings = UserSettings.query.first()
            if settings:
                if not token and getattr(settings, "telegram_bot_token", None):
                    token = settings.telegram_bot_token.strip()
                if not chat and getattr(settings, "telegram_chat_id", None):
                    chat = settings.telegram_chat_id.strip()
    except Exception as exc:
        logger.debug("Could not read Telegram credentials from DB: %s", exc)

    # Check environment variables
    if not token:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not chat:
        chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    # Check config.py fallback
    if not token or not chat:
        try:
            from config import active_config
            if not token:
                token = getattr(active_config, "TELEGRAM_BOT_TOKEN", "").strip()
            if not chat:
                chat = getattr(active_config, "TELEGRAM_CHAT_ID", "").strip()
        except Exception:
            pass

    return token, chat


def is_telegram_configured(
    bot_token: str | None = None,
    chat_id: str | None = None,
) -> bool:
    """Return True if both bot_token and chat_id are configured and non-empty."""
    token, chat = get_telegram_credentials(bot_token, chat_id)
    return bool(token and chat)


def format_job_message(job: Any) -> str:
    """
    Format a Job ORM row or dict into a rich, structured HTML message for Telegram.
    Safely escapes all dynamic strings to prevent Telegram HTML parsing errors.
    """
    org = html.escape(str(getattr(job, "organization", "") or "Government of India"))
    title = html.escape(str(getattr(job, "title", "") or "Recruitment Notification"))
    category = html.escape(str(getattr(job, "exam_category", "") or "Other"))
    pay = html.escape(str(getattr(job, "pay_level_or_ctc", "") or ""))
    qual = html.escape(str(getattr(job, "educational_qualifications", "") or ""))
    last_date = html.escape(str(getattr(job, "last_date", "") or "Refer Notice"))
    exam_date = html.escape(str(getattr(job, "exam_date", "") or "To be notified"))
    age = html.escape(str(getattr(job, "age_limit_details", "") or "Refer Notice"))
    selection = html.escape(str(getattr(job, "selection_summary", "") or ""))

    # GATE badge
    gate_req = getattr(job, "gate_required", False)
    gate_text = "⚠️ <b>Yes (GATE Score Required)</b>" if gate_req else "✅ <b>No (Direct / Written Exam)</b>"

    # Category badge
    cat_emojis = {
        "Technical CS/IT": "💻",
        "Competitive Exam": "🏛",
        "PSU": "⚡",
        "Military": "🎖",
        "Banking": "🏦",
        "Other": "📋",
    }
    cat_emoji = cat_emojis.get(getattr(job, "exam_category", "Other"), "📋")

    lines = [
        "🚨 <b>NEW GOVT RECRUITMENT ALERT</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🏢 <b>Organisation:</b> {org}",
        f"💼 <b>Post / Exam:</b> {title}",
        f"{cat_emoji} <b>Category:</b> {category}",
        f"🎯 <b>GATE:</b> {gate_text}",
    ]

    if pay:
        lines.append(f"💰 <b>Pay / Scale:</b> {pay}")
    if qual:
        lines.append(f"🎓 <b>Qualifications:</b> {qual}")
    lines.append(f"⏳ <b>Last Date:</b> {last_date}")
    if exam_date and exam_date != "To be notified":
        lines.append(f"📝 <b>Exam Date:</b> {exam_date}")
    if age and age != "Refer Notice":
        lines.append(f"🎂 <b>Age Limit:</b> {age}")
    if selection:
        lines.append(f"📋 <b>Selection:</b> {selection}")

    # Links
    notice_url = getattr(job, "notification_url", "") or ""
    pdf_url = getattr(job, "pdf_url", "") or ""

    links = []
    if notice_url:
        links.append(f'<a href="{html.escape(notice_url)}">🌐 Official Portal</a>')
    if pdf_url:
        links.append(f'<a href="{html.escape(pdf_url)}">📄 Download PDF</a>')

    if links:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(" | ".join(links))

    job_id = getattr(job, "id", None)
    job_ref = f" (ID #{job_id})" if job_id else ""
    lines.append(f"\n<i>⚡ Tracked by GovRecruitmentTracker{job_ref}</i>")

    return "\n".join(lines)


def send_message(
    text: str,
    chat_id: str | None = None,
    bot_token: str | None = None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
    timeout: int = 10,
    session: requests.Session | None = None,
) -> bool:
    """
    Synchronously send a message to a Telegram chat via HTTP POST.

    Returns:
        bool: True if Telegram API responded with 200 OK, False otherwise.
    """
    token, target_chat = get_telegram_credentials(bot_token, chat_id)
    if not token or not target_chat:
        logger.debug("Telegram credentials not set — skipping notification.")
        return False

    url = _TELEGRAM_API_BASE.format(token=token, method="sendMessage")
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }

    http = session or requests
    try:
        response = http.post(url, json=payload, timeout=timeout)
        if response.status_code == 200:
            logger.info("Telegram notification delivered to chat %s", target_chat)
            return True
        else:
            logger.warning(
                "Telegram API error: HTTP %d: %s",
                response.status_code,
                response.text,
            )
            return False
    except Exception as exc:
        logger.error("Failed to send Telegram message: %s", exc)
        return False


def send_message_async(
    text: str,
    chat_id: str | None = None,
    bot_token: str | None = None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
    timeout: int = 10,
) -> threading.Thread:
    """
    Non-blocking helper: Spawns a background daemon thread to send a Telegram message.
    Returns the started Thread object immediately.
    """
    def _worker():
        send_message(
            text=text,
            chat_id=chat_id,
            bot_token=bot_token,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            timeout=timeout,
        )

    thread = threading.Thread(
        target=_worker,
        name=f"telegram-send-{time.time_ns()}",
        daemon=True,
    )
    thread.start()
    return thread


def notify_new_job(
    job: Any,
    chat_id: str | None = None,
    bot_token: str | None = None,
    async_send: bool = True,
) -> bool | threading.Thread:
    """
    Send a recruitment notification for a single Job.

    Args:
        job:        Job ORM instance or compatible duck-typed object.
        chat_id:    Optional Telegram chat ID override.
        bot_token:  Optional Telegram bot token override.
        async_send: If True (default), dispatches in a daemon thread and returns
                    the Thread. If False, sends synchronously and returns bool.

    Returns:
        threading.Thread if async_send is True, or bool if async_send is False.
    """
    if not is_telegram_configured(bot_token, chat_id):
        logger.debug("Telegram not configured — skipping notify_new_job.")
        return False if not async_send else threading.Thread()

    message = format_job_message(job)
    if async_send:
        return send_message_async(message, chat_id=chat_id, bot_token=bot_token)
    return send_message(message, chat_id=chat_id, bot_token=bot_token)


def notify_jobs_batch(
    jobs: list[Any],
    chat_id: str | None = None,
    bot_token: str | None = None,
    async_send: bool = True,
    interval_sec: float = 0.5,
) -> int | threading.Thread:
    """
    Send notifications for a list of newly discovered jobs.

    If async_send=True, runs in a background thread with an interval between
    messages to avoid hitting Telegram API rate limits (returns the Thread).
    If async_send=False, sends synchronously and returns count of successful deliveries.
    """
    if not jobs:
        return 0 if not async_send else threading.Thread()

    if not is_telegram_configured(bot_token, chat_id):
        logger.debug("Telegram not configured — skipping notify_jobs_batch.")
        return 0 if not async_send else threading.Thread()

    def _batch_worker() -> int:
        delivered = 0
        for i, job in enumerate(jobs):
            if i > 0 and interval_sec > 0:
                time.sleep(interval_sec)
            msg = format_job_message(job)
            if send_message(msg, chat_id=chat_id, bot_token=bot_token):
                delivered += 1
        logger.info("Delivered %d/%d Telegram job notifications in batch.", delivered, len(jobs))
        return delivered

    if async_send:
        thread = threading.Thread(
            target=_batch_worker,
            name=f"telegram-batch-{time.time_ns()}",
            daemon=True,
        )
        thread.start()
        return thread

    return _batch_worker()


def send_test_message(
    chat_id: str | None = None,
    bot_token: str | None = None,
) -> tuple[bool, str]:
    """
    Send a verification test message to test bot credentials.

    Returns:
        tuple[bool, str]: (Success, Status / Error description).
    """
    token, target_chat = get_telegram_credentials(bot_token, chat_id)
    if not token or not target_chat:
        return False, "Telegram credentials not configured (bot token and chat ID required)."

    text = (
        "🚀 <b>GovRecruitmentTracker — Test Message</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Your Telegram bot is successfully connected!\n"
        "You will receive instant alerts whenever new Indian Government "
        "recruitment notifications matching your criteria are discovered."
    )

    url = _TELEGRAM_API_BASE.format(token=token, method="sendMessage")
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True, "Test notification delivered successfully."
        try:
            err_data = resp.json()
            description = err_data.get("description", resp.text)
        except Exception:
            description = resp.text
        return False, f"Telegram API error (HTTP {resp.status_code}): {description}"
    except Exception as exc:
        return False, f"Connection failed: {exc}"


# ── CLI test runner ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if "--test" in sys.argv:
        ok, msg = send_test_message()
        print(f"Result: {ok} — {msg}")
        sys.exit(0 if ok else 1)
    print("Usage: python telegram_notifier.py --test")
