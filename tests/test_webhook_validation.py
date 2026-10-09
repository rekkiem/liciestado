"""C3/A4: tests del validador real app.net_safety.validar_webhook_url."""
from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from app.net_safety import validar_webhook_url


def _fake_addrinfo(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


@pytest.mark.parametrize("url", [
    "https://169.254.169.254/x",
    "https://[::ffff:127.0.0.1]/x",
    "https://127.1/x",
    "https://2130706433/x",
    "https://localhost/x",
    "https://[::1]/x",
    "http://example.com/x",
])
def test_blocked_literal_or_scheme(url):
    with patch("app.net_safety.socket.getaddrinfo") as gai:
        if "169.254" in url:
            gai.return_value = _fake_addrinfo("169.254.169.254")
        elif "127.1" in url or "2130706433" in url:
            gai.return_value = _fake_addrinfo("127.0.0.1")
        elif "::ffff:127" in url or "::1" in url:
            gai.return_value = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0))]
        elif "localhost" in url:
            gai.return_value = _fake_addrinfo("127.0.0.1")
        else:
            gai.return_value = _fake_addrinfo("93.184.216.34")
        ok, msg = validar_webhook_url(url)
        assert ok is False, f"should block {url}: {msg}"


@pytest.mark.parametrize("ip", [
    "10.0.0.1", "192.168.1.1", "172.16.0.5", "172.31.255.1", "127.0.0.1",
])
def test_blocked_resolved_private(ip):
    with patch("app.net_safety.socket.getaddrinfo", return_value=_fake_addrinfo(ip)):
        ok, msg = validar_webhook_url("https://evil.example/hook")
        assert ok is False


def test_allowed_public_google_ip():
    with patch("app.net_safety.socket.getaddrinfo", return_value=_fake_addrinfo("172.217.16.14")):
        ok, msg = validar_webhook_url("https://hooks.example.com/x")
        assert ok is True, msg


def test_allowed_public_hostname():
    with patch("app.net_safety.socket.getaddrinfo", return_value=_fake_addrinfo("93.184.216.34")):
        ok, msg = validar_webhook_url("https://example.com/webhook")
        assert ok is True, msg


def test_rejects_credentials():
    ok, msg = validar_webhook_url("https://user:pass@example.com/x")
    assert ok is False


def test_rejects_too_long():
    ok, msg = validar_webhook_url("https://example.com/" + ("a" * 500))
    assert ok is False
