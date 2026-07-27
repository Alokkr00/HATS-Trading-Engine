"""Slack and Telegram multi-channel alert notifier utility with severity-based routing."""

from __future__ import annotations

import os
import json
import logging
import urllib.request
import urllib.parse
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def send_alert(message: str, severity: str = "INFO") -> None:
    """
    Sends an alert message to Slack and/or Telegram depending on the severity level.
    
    Supported Environment Variables:
        - TELEGRAM_BOT_TOKEN: Telegram Bot authentication token (Required for Telegram alerts).
        - TELEGRAM_CHAT_ID: Default target Telegram chat ID.
        - TELEGRAM_CHAT_ID_<SEVERITY>: Severity-specific Telegram chat ID (e.g. TELEGRAM_CHAT_ID_CRITICAL).
        
        - SLACK_WEBHOOK_URL: Default target Slack incoming webhook URL.
        - SLACK_WEBHOOK_URL_<SEVERITY>: Severity-specific Slack incoming webhook URL (e.g. SLACK_WEBHOOK_URL_CRITICAL).
        
    If no endpoints are configured for a channel/severity, that notification channel is bypassed.
    This utility is fail-safe; delivery errors are logged but never raised to disrupt system execution.
    """
    load_dotenv()
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
                    "parse_mode": "Markdown",
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    res_data = response.read().decode("utf-8")
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
                method="POST"
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
