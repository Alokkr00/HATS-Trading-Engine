"""Unit tests for the Slack & Telegram multi-channel notifier utility."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch
import pytest

from src.utils.notifier import send_alert, send_telegram_alert


@pytest.fixture(autouse=True)
def enable_notifier_testing(monkeypatch):
    """Enable actual execution of send_alert during notifier module tests."""
    monkeypatch.setenv("TESTING_NOTIFIER", "1")


@pytest.fixture
def mock_urlopen():
    """Mocks urllib.request.urlopen context manager."""
    with patch("urllib.request.urlopen") as mock_open:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ok": true}'
        mock_response.__enter__.return_value = mock_response
        mock_open.return_value = mock_response
        yield mock_open


def test_notifier_telegram_only(mock_urlopen):
    """Test Telegram routing when Slack is not configured."""
    env_vars = {
        "TELEGRAM_BOT_TOKEN": "mock_token",
        "TELEGRAM_CHAT_ID": "mock_chat_id",
        "SLACK_WEBHOOK_URL": "",
    }
    with patch.dict(os.environ, env_vars):
        send_alert("Hello world", severity="INFO")
        
        # Verify urlopen called for Telegram
        assert mock_urlopen.call_count == 1
        args, kwargs = mock_urlopen.call_args
        req = args[0]
        assert "api.telegram.org/botmock_token/sendMessage" in req.full_url
        
        # Check payload
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["chat_id"] == "mock_chat_id"
        assert payload["text"] == "Hello world"
        assert payload["parse_mode"] == "HTML"


def test_notifier_slack_only(mock_urlopen):
    """Test Slack routing when Telegram is not configured."""
    env_vars = {
        "TELEGRAM_BOT_TOKEN": "",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/mock_webhook",
    }
    with patch.dict(os.environ, env_vars):
        send_alert("Hello Slack", severity="INFO")
        
        # Verify urlopen called for Slack
        assert mock_urlopen.call_count == 1
        args, kwargs = mock_urlopen.call_args
        req = args[0]
        assert req.full_url == "https://hooks.slack.com/services/mock_webhook"
        
        # Check payload
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["text"] == "Hello Slack"


def test_notifier_severity_routing(mock_urlopen):
    """Test that critical severity is routed to specific channels and prefixes are formatted."""
    env_vars = {
        "TELEGRAM_BOT_TOKEN": "mock_token",
        "TELEGRAM_CHAT_ID": "default_chat",
        "TELEGRAM_CHAT_ID_CRITICAL": "critical_chat",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/default",
        "SLACK_WEBHOOK_URL_CRITICAL": "https://hooks.slack.com/critical",
    }
    with patch.dict(os.environ, env_vars):
        send_alert("Core database is down!", severity="CRITICAL")
        
        assert mock_urlopen.call_count == 2
        
        # Verify Telegram call targets critical_chat
        tg_req = next(call[0][0] for call in mock_urlopen.call_args_list if "telegram" in call[0][0].full_url)
        tg_payload = json.loads(tg_req.data.decode("utf-8"))
        assert tg_payload["chat_id"] == "critical_chat"
        assert tg_payload["text"] == "Core database is down!"
        
        # Verify Slack call targets critical webhook with emoji prefix
        slack_req = next(call[0][0] for call in mock_urlopen.call_args_list if "slack" in call[0][0].full_url)
        assert slack_req.full_url == "https://hooks.slack.com/critical"
        slack_payload = json.loads(slack_req.data.decode("utf-8"))
        assert slack_payload["text"] == "🚨 *[CRITICAL]* Core database is down!"


def test_notifier_error_safety(mock_urlopen):
    """Test that network delivery failures do not raise exceptions."""
    mock_urlopen.side_effect = Exception("Connection Timeout")
    env_vars = {
        "TELEGRAM_BOT_TOKEN": "mock_token",
        "TELEGRAM_CHAT_ID": "mock_chat_id",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/mock_webhook",
    }
    with patch.dict(os.environ, env_vars):
        with patch("time.sleep"):
            # Should not raise any exception
            send_alert("Failing gracefully", severity="ERROR")
            assert mock_urlopen.call_count >= 2


def test_telegram_html_failure_falls_back_to_plain_text(mock_urlopen):
    """
    If Telegram returns an HTTP 400 error (e.g. invalid HTML tags),
    it must fallback to sending as plain text (parse_mode removed).
    """
    import urllib.error
    # First call: HTTPError 400 Bad Request (can't parse entities)
    http_error = urllib.error.HTTPError(
        url="https://api.telegram.org",
        code=400,
        msg="Bad Request: can't parse entities",
        hdrs={},
        fp=None
    )
    # Second call (fallback): succeeds
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"ok": true}'
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False

    mock_urlopen.side_effect = [http_error, mock_response]

    env_vars = {
        "TELEGRAM_BOT_TOKEN": "mock_token",
        "TELEGRAM_CHAT_ID": "mock_chat_id",
        "SLACK_WEBHOOK_URL": "",
    }
    with patch.dict(os.environ, env_vars):
        with patch("time.sleep"):
            send_alert("Test with unclosed <b tag", severity="INFO")

    assert mock_urlopen.call_count == 2
    # Second call should not have parse_mode in payload
    fallback_req = mock_urlopen.call_args_list[1][0][0]
    payload = json.loads(fallback_req.data.decode("utf-8"))
    assert "parse_mode" not in payload
    assert payload["text"] == "Test with unclosed <b tag"


def test_backwards_compatible_wrapper(mock_urlopen):
    """Test that send_telegram_alertwrapper deduces severity and logs properly."""
    env_vars = {
        "TELEGRAM_BOT_TOKEN": "mock_token",
        "TELEGRAM_CHAT_ID": "default_chat",
        "TELEGRAM_CHAT_ID_CRITICAL": "critical_chat",
    }
    with patch.dict(os.environ, env_vars):
        # 1. Deduce CRITICAL
        send_telegram_alert("RISK-OFF triggered immediately")
        args, kwargs = mock_urlopen.call_args
        req = args[0]
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["chat_id"] == "critical_chat"
        
        # 2. Deduce WARNING
        mock_urlopen.reset_mock()
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "mock_token",
            "TELEGRAM_CHAT_ID": "default_chat",
            "TELEGRAM_CHAT_ID_WARNING": "warn_chat",
        }
        with patch.dict(os.environ, env_vars):
            send_telegram_alert("Warning: Breaker status active")
            args, kwargs = mock_urlopen.call_args
            req = args[0]
            payload = json.loads(req.data.decode("utf-8"))
            assert payload["chat_id"] == "warn_chat"


def test_html_parse_mode_with_financial_special_chars(mock_urlopen):
    """
    Smoke test: messages containing financial special chars ($, ., (, )) must be
    delivered with parse_mode=HTML. With old Markdown v1 mode these caused silent
    HTTP 400 rejections from the Telegram API.
    """
    env_vars = {
        "TELEGRAM_BOT_TOKEN": "mock_token",
        "TELEGRAM_CHAT_ID": "mock_chat_id",
        "SLACK_WEBHOOK_URL": "",
    }
    msg = (
        "📈 <b>H.A.T.S Execution Fill</b>:\n"
        "• <b>Side</b>: BUY\n"
        "• <b>Ticker</b>: AAPL\n"
        "• <b>Shares</b>: 10\n"
        "• <b>Price</b>: $175.32"
    )
    with patch.dict(os.environ, env_vars):
        send_alert(msg, severity="INFO")

    assert mock_urlopen.call_count == 1
    req = mock_urlopen.call_args[0][0]
    payload = json.loads(req.data.decode("utf-8"))
    assert payload["parse_mode"] == "HTML"
    assert "$175.32" in payload["text"]
    assert "<b>" in payload["text"]


def test_telegram_retry_on_transient_failure(mock_urlopen):
    """
    Retry logic test: if urlopen raises on the first attempt but succeeds on the
    second, the alert must still be delivered (call_count == 2, no exception raised).
    """
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"ok": true}'
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False

    # First call raises, second call succeeds
    mock_urlopen.side_effect = [Exception("Transient network error"), mock_response]

    env_vars = {
        "TELEGRAM_BOT_TOKEN": "mock_token",
        "TELEGRAM_CHAT_ID": "mock_chat_id",
        "SLACK_WEBHOOK_URL": "",
    }
    with patch.dict(os.environ, env_vars):
        with patch("time.sleep"):  # Don't actually sleep in tests
            send_alert("Retry smoke test", severity="INFO")

    # Should have retried: 1 failed + 1 success = 2 total urlopen calls
    assert mock_urlopen.call_count == 2
