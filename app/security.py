"""
app/security.py — Seguridad: CSRF, rate limiting auth, security headers.
"""
from __future__ import annotations
import time, logging
from collections import defaultdict
from threading import Lock
from functools import wraps
from flask import request, abort, g
from flask_wtf.csrf import CSRFProtect

logger = logging.getLogger(__name__)

# CSRF global
csrf = CSRFProtect()

# ── Rate limiter simple en memoria (auth endpoints) ───────────────────────────
_auth_attempts: dict = defaultdict(list)
_auth_lock = Lock()
_MAX_ATTEMPTS = 10   # intentos
_WINDOW_SEC   = 300  # en 5 minutos

def check_auth_rate_limit():
    """Llama desde login POST. Abort 429 si supera el límite."""
    ip = request.remote_addr or "unknown"
    now = time.monotonic()
    with _auth_lock:
        attempts = [t for t in _auth_attempts[ip] if now - t < _WINDOW_SEC]
        attempts.append(now)
        _auth_attempts[ip] = attempts
        if len(attempts) > _MAX_ATTEMPTS:
            logger.warning("Rate limit auth superado para IP: %s (%d intentos)", ip, len(attempts))
            abort(429)

# ── Security headers ──────────────────────────────────────────────────────────
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]        = "DENY"
    response.headers["X-XSS-Protection"]       = "1; mode=block"
    response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    # CSP permisivo para Chart.js desde CDN
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self';"
    )
    return response


def check_insecure_defaults():
    """Llama al arranque. Warning en dev; RuntimeError en production."""
    import os
    from config import settings
    bad = []
    if settings.SECRET_KEY in ("cambia-esto-en-produccion", "change-me", "secret", ""):
        bad.append("SECRET_KEY")
    if settings.DASHBOARD_PASS in ("admin", "password", "1234", ""):
        bad.append("DASHBOARD_PASS")
    if not bad:
        return
    msg = (
        "DEFAULTS INSEGUROS EN USO: %s. Cambia estas variables en .env antes de producción."
        % ", ".join(bad)
    )
    env = (os.environ.get("FLASK_ENV") or os.environ.get("ENV") or "").lower()
    if env == "production":
        raise RuntimeError(msg)
    logger.warning("⚠️  %s", msg)
