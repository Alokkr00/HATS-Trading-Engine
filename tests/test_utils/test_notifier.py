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
        assert payload["parse_mode"] == "Markdown"


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
        # Should not raise any exception
        send_alert("Failing gracefully", severity="ERROR")
        assert mock_urlopen.call_count == 2


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
