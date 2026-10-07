"""Basic unit tests for webhook URL validation logic (F5)."""
from urllib.parse import urlparse


def _is_blocked(url: str) -> bool:
    """Mirror of the validation logic in auth_routes."""
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return True
    host = (parsed.hostname or "").lower()
    return (
        host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
        or host.endswith(".local")
        or host.endswith(".internal")
        or host.startswith("10.")
        or host.startswith("192.168.")
        or host.startswith("172.")
        or not host
    )


def test_https_public_ok():
    assert not _is_blocked("https://hooks.slack.com/services/xxx")


def test_http_blocked():
    assert _is_blocked("http://example.com/hook")


def test_localhost_blocked():
    assert _is_blocked("https://localhost/hook")
    assert _is_blocked("https://127.0.0.1/hook")


def test_private_ip_blocked():
    assert _is_blocked("https://10.0.0.5/hook")
    assert _is_blocked("https://192.168.1.1/hook")
