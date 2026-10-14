"""Tests Objetivo 1 — rate limit, Retry-After, redaction de ticket, circuit breaker."""
from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.api_client import (
    MercadoPublicoClient,
    QuotaExhaustedException,
    RateLimitedException,
    RateLimiter,
    ApiClientException,
    redact_secrets,
    _parse_retry_after,
    _backoff_with_jitter,
    make_enrich_client,
)


TICKET = "SUPER-SECRET-TICKET-ABC123XYZ"


def _mock_response(status: int, json_data=None, headers=None, text=""):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.headers = headers or {}
    resp.text = text or ("" if json_data is None else str(json_data))
    resp.json.return_value = json_data if json_data is not None else {}
    if status >= 400:
        http_err = requests.exceptions.HTTPError(response=resp)
        resp.raise_for_status.side_effect = http_err
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_redact_secrets_removes_ticket_param():
    msg = f"GET https://api.example/x?ticket={TICKET}&pagina=1 failed"
    out = redact_secrets(msg, TICKET)
    assert TICKET not in out
    assert "[REDACTED]" in out


def test_redact_secrets_removes_plain_ticket():
    msg = f"error with ticket: {TICKET}"
    out = redact_secrets(msg, TICKET)
    assert TICKET not in out


def test_redact_secrets_case_insensitive():
    msg = f"Ticket={TICKET}"
    out = redact_secrets(msg, TICKET)
    assert TICKET not in out


def test_parse_retry_after_seconds():
    assert _parse_retry_after("12") == 12.0
    assert _parse_retry_after("0") == 0.0


def test_parse_retry_after_caps_at_1h():
    assert _parse_retry_after("99999") == 3600.0


def test_parse_retry_after_invalid():
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("") is None
    assert _parse_retry_after("not-a-date") is None


def test_backoff_with_jitter_in_range():
    for attempt in range(5):
        v = _backoff_with_jitter(attempt, base=2.0, cap=30.0)
        # equal jitter: [exp/2, exp] ⊆ [0, cap]
        assert 0 <= v <= 30.0


def test_backoff_429_floor_min_2s():
    """Sin Retry-After, la espera de 429 no debe ser casi 0 (piso 2s)."""
    for attempt in range(8):
        v = _backoff_with_jitter(attempt, base=5.0, cap=90.0, floor=2.0)
        assert v >= 2.0, f"attempt={attempt} wait={v}"
        assert v <= 90.0


def test_rate_limiter_daily_quota():
    rl = RateLimiter(per_second=100, per_day=3)
    rl.acquire()
    rl.acquire()
    rl.acquire()
    with pytest.raises(QuotaExhaustedException):
        rl.acquire()


def test_rate_limiter_circuit_breaker():
    rl = RateLimiter(per_second=100, per_day=10_000, circuit_threshold=2, circuit_pause_sec=0.3)
    rl.record_429_cycle_exhausted()
    assert not rl.circuit_open
    rl.record_429_cycle_exhausted()
    assert rl.circuit_open
    with pytest.raises(QuotaExhaustedException, match="Circuit breaker"):
        rl.acquire()
    time.sleep(0.35)
    rl.acquire()


def test_rate_limiter_success_resets_consecutive():
    rl = RateLimiter(per_second=100, per_day=10_000, circuit_threshold=3, circuit_pause_sec=60)
    rl.record_429_cycle_exhausted()
    rl.record_429_cycle_exhausted()
    rl.record_success()
    rl.record_429_cycle_exhausted()
    assert not rl.circuit_open


@patch("app.api_client.time.sleep", return_value=None)
def test_client_respects_retry_after(mock_sleep):
    client = MercadoPublicoClient(ticket=TICKET, per_second=100, per_day=10_000, max_retries=3)
    responses = [
        _mock_response(429, headers={"Retry-After": "7"}),
        _mock_response(200, json_data={"Listado": [{"CodigoExterno": "X1"}]}),
    ]
    client.session.get = MagicMock(side_effect=responses)
    data = client._get("publico/licitaciones.json", {"codigo": "X1"})
    assert data["Listado"][0]["CodigoExterno"] == "X1"
    slept = [c.args[0] for c in mock_sleep.call_args_list if c.args]
    assert any(6.5 <= s <= 9.0 for s in slept), f"sleeps={slept}"


@patch("app.api_client.time.sleep", return_value=None)
def test_client_exhausts_429_raises_rate_limited(mock_sleep):
    client = MercadoPublicoClient(ticket=TICKET, per_second=100, per_day=10_000, max_retries=3)
    client.session.get = MagicMock(return_value=_mock_response(429, headers={"Retry-After": "1"}))
    with pytest.raises(RateLimitedException) as exc_info:
        client._get("publico/licitaciones.json")
    msg = str(exc_info.value)
    assert TICKET not in msg
    assert "429" in msg or "frenar" in msg.lower()


@patch("app.api_client.time.sleep", return_value=None)
def test_ticket_never_in_exception_message(mock_sleep):
    client = MercadoPublicoClient(ticket=TICKET, per_second=100, per_day=10_000, max_retries=2)

    def boom(*a, **k):
        raise requests.exceptions.RequestException(
            f"401 Unauthorized ticket={TICKET} url=https://api/x?ticket={TICKET}"
        )

    client.session.get = MagicMock(side_effect=boom)
    with pytest.raises(ApiClientException) as exc_info:
        client._get("publico/licitaciones.json")
    assert TICKET not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value) or "ticket" in str(exc_info.value).lower()


@patch("app.api_client.time.sleep", return_value=None)
def test_ticket_not_in_logs(mock_sleep, caplog):
    client = MercadoPublicoClient(ticket=TICKET, per_second=100, per_day=10_000, max_retries=2)

    def boom(*a, **k):
        raise requests.exceptions.RequestException(f"fail ticket={TICKET}")

    client.session.get = MagicMock(side_effect=boom)
    with caplog.at_level(logging.ERROR, logger="app.api_client"):
        with pytest.raises(ApiClientException):
            client._get("publico/licitaciones.json")
    for record in caplog.records:
        assert TICKET not in record.getMessage()


@patch("app.api_client.time.sleep", return_value=None)
def test_quota_exhausted_stops_cleanly(mock_sleep):
    client = MercadoPublicoClient(ticket=TICKET, per_second=100, per_day=1, max_retries=2)
    client.session.get = MagicMock(
        return_value=_mock_response(200, json_data={"Listado": []})
    )
    client._get("publico/licitaciones.json")
    with pytest.raises(QuotaExhaustedException):
        client._get("publico/licitaciones.json")


def test_make_enrich_client_uses_slow_rate(monkeypatch):
    monkeypatch.setattr("config.settings.API_ENRICH_RATE_PER_SECOND", 2.0)
    monkeypatch.setattr("config.settings.API_RATE_PER_DAY", 10_000)
    c = make_enrich_client(ticket="t")
    assert c.rate_limiter.per_second == 2.0


@patch("app.api_client.time.sleep", return_value=None)
def test_get_licitacion_detalle_propagates_rate_limit(mock_sleep):
    client = MercadoPublicoClient(ticket=TICKET, per_second=100, per_day=10_000, max_retries=2)
    client.session.get = MagicMock(return_value=_mock_response(429, headers={"Retry-After": "1"}))
    with pytest.raises(RateLimitedException):
        client.get_licitacion_detalle("CODE-1")


@patch("app.api_client.time.sleep", return_value=None)
def test_max_retries_default_is_five(mock_sleep):
    client = MercadoPublicoClient(ticket=TICKET, per_second=100, per_day=10_000)
    assert client.max_retries == 5
    client.session.get = MagicMock(return_value=_mock_response(429, headers={"Retry-After": "0"}))
    with pytest.raises(RateLimitedException):
        client._get("publico/licitaciones.json")
    assert client.session.get.call_count == 5


def test_api_rate_per_day_cap(monkeypatch):
    monkeypatch.setenv("API_RATE_PER_DAY", "10001")
    import importlib
    import config as cfg
    with pytest.raises(Exception):
        importlib.reload(cfg)
