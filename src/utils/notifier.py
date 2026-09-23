"""Slack and Telegram multi-channel alert notifier utility with severity-based routing."""

from __future__ import annotations

import os
import json
import logging
import time
import urllib.request
import urllib.parse
from dotenv import load_dotenv

# Load .env once at module import time (no-op on Render/CI where env vars are injected directly)
load_dotenv()

logger = logging.getLogger(__name__)

import urllib.error

# Startup warnings: emit once if Telegram credentials are absent so they surface in boot logs
if not os.getenv("TELEGRAM_BOT_TOKEN"):
    logger.warning(
        "TELEGRAM_BOT_TOKEN is not set — Telegram notifications will be silently skipped. "
        "Set this environment variable in your Render dashboard or CI secrets."
    )
if not os.getenv("TELEGRAM_CHAT_ID"):
    logger.warning(
        "TELEGRAM_CHAT_ID is not set — Telegram notifications will be silently skipped. "
        "Set this environment variable in your Render dashboard or CI secrets."
    )

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TELEGRAM_TIMEOUT = 15  # seconds — increased from 5s to survive Render cold-boot latency
_TELEGRAM_MAX_RETRIES = 3
_TELEGRAM_RETRY_BACKOFF = 2  # seconds between retry attempts


def _http_post_with_retry(req: urllib.request.Request, timeout: int, max_retries: int, backoff: float) -> str:
    """
    Execute an HTTP POST with exponential-ish backoff retries.
    
    Returns the decoded response body on success.
    Raises the last exception if all attempts are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except Exception as exc:
            last_exc = exc
            # If HTTP 4xx client error (e.g. 400 Bad Request / entity parse error), don't retry with same payload
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                raise
            if attempt < max_retries:
                logger.warning(
                    f"HTTP POST attempt {attempt}/{max_retries} failed: {exc}. "
                    f"Retrying in {backoff * attempt}s..."
                )
                time.sleep(backoff * attempt)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def send_alert(message: str, severity: str = "INFO") -> None:
    """
    Sends an alert message to Slack and/or Telegram depending on the severity level.

    Telegram messages are formatted with HTML (parse_mode=HTML) — use <b>bold</b>,
    <i>italic</i>, <code>code</code> tags in message strings. This avoids the silent
    rejection that Telegram's strict Markdown v1 mode causes for characters like
    $, (, ), ., !, [, ` that appear in financial messages. If HTML rendering fails
    (e.g. unclosed tags), it automatically falls back to sending as plain text.

    Supported Environment Variables:
        - TELEGRAM_BOT_TOKEN: Telegram Bot authentication token (Required for Telegram alerts).
        - TELEGRAM_CHAT_ID: Default target Telegram chat ID.
        - TELEGRAM_CHAT_ID_<SEVERITY>: Severity-specific Telegram chat ID (e.g. TELEGRAM_CHAT_ID_CRITICAL).

        - SLACK_WEBHOOK_URL: Default target Slack incoming webhook URL.
        - SLACK_WEBHOOK_URL_<SEVERITY>: Severity-specific Slack incoming webhook URL (e.g. SLACK_WEBHOOK_URL_CRITICAL).

    If no endpoints are configured for a channel/severity, that notification channel is bypassed.
    This utility is fail-safe; delivery errors are logged but never raised to disrupt system execution.
    """
    import sys
    if "pytest" in sys.modules and os.getenv("TESTING_NOTIFIER") != "1":
        logger.debug("Bypassing notifier alert sending in test/CI environment.")
        return
    severity_upper = severity.upper()

    # 1. Route and Deliver Telegram Alert
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if telegram_token:
        # Resolve chat ID: check severity-specific first, fallback to default
        chat_id = os.getenv(f"TELEGRAM_CHAT_ID_{severity_upper}")
        if not chat_id:
            chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if chat_id:
            try:
                url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": message,
                    # HTML parse_mode: avoids silent rejections from Telegram's strict Markdown v1
                    # which rejects unescaped $, (, ), ., !, [, ` characters common in financial messages.
                    "parse_mode": "HTML",
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    res_data = _http_post_with_retry(
                        req,
                        timeout=_TELEGRAM_TIMEOUT,
                        max_retries=_TELEGRAM_MAX_RETRIES,
                        backoff=_TELEGRAM_RETRY_BACKOFF,
                    )
                except Exception as post_err:
                    # If HTML parsing failed or HTTP 400 Bad Request, retry as plain text fallback
                    logger.warning(f"Telegram HTML send failed ({post_err}). Retrying as plain text...")
                    payload.pop("parse_mode", None)
                    fallback_req = urllib.request.Request(
                        url,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    res_data = _http_post_with_retry(
                        fallback_req,
                        timeout=_TELEGRAM_TIMEOUT,
                        max_retries=1,
                        backoff=1.0,
                    )
                logger.debug(f"Telegram notification sent successfully: {res_data}")
            except Exception as e:
                logger.error(f"Failed to transmit Telegram notification alert (Severity: {severity}): {e}")
        else:
            logger.debug(f"Telegram Chat ID not configured for severity {severity}. Skipping.")
    else:
        logger.debug("Telegram Bot Token not configured. Skipping Telegram notification.")

    # 2. Route and Deliver Slack Alert
    slack_webhook = os.getenv(f"SLACK_WEBHOOK_URL_{severity_upper}")
    if not slack_webhook:
        slack_webhook = os.getenv("SLACK_WEBHOOK_URL")

    if slack_webhook:
        try:
            # Format message prefix based on severity
            prefix = ""
            if severity_upper == "CRITICAL":
                prefix = "🚨 *[CRITICAL]* "
            elif severity_upper == "ERROR":
                prefix = "⚠️ *[ERROR]* "
            elif severity_upper == "WARNING":
                prefix = "🔔 *[WARNING]* "

            payload = {
                "text": f"{prefix}{message}"
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                slack_webhook,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = response.read().decode("utf-8")
                logger.debug(f"Slack notification sent successfully: {res_data}")
        except Exception as e:
            logger.error(f"Failed to transmit Slack notification alert (Severity: {severity}): {e}")
    else:
        logger.debug(f"Slack Webhook not configured for severity {severity}. Skipping.")


def send_telegram_alert(message: str) -> None:
    """
    Backwards-compatible wrapper that routes alerts through the upgraded send_alert engine.
    Deduces severity level from message keywords.

    Message strings should use HTML tags for formatting:
        <b>bold</b>, <i>italic</i>, <code>inline code</code>
    Do NOT use Markdown syntax (**bold**, `code`, _italic_) — it will be rendered as literal text.
    """
    severity = "INFO"
    msg_upper = message.upper()

    if any(keyword in msg_upper for keyword in ["CRITICAL", "HALT", "RISK-OFF", "CRASH"]):
        severity = "CRITICAL"
    elif any(keyword in msg_upper for keyword in ["ERROR", "FAIL", "EXCEPTION"]):
        severity = "ERROR"
    elif any(keyword in msg_upper for keyword in ["WARNING", "WARN", "BREAKER", "REJECTED"]):
        severity = "WARNING"

    send_alert(message, severity=severity)
