"""pytest fixtures for LiciEstado."""
import os
import sys
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Stub pydantic_settings if missing (sandbox CI sin el paquete; prod lo tiene en requirements)
try:
    import pydantic_settings  # noqa: F401
except ImportError:  # pragma: no cover
    from pydantic import BaseModel

    class _BaseSettings(BaseModel):
        model_config = {"extra": "ignore"}

        def __init__(self, **data):
            fields = getattr(self.__class__, "model_fields", {}) or {}
            for name in fields:
                if name in os.environ and name not in data:
                    data[name] = os.environ[name]
            super().__init__(**data)

    mod = type(sys)("pydantic_settings")
    mod.BaseSettings = _BaseSettings
    sys.modules["pydantic_settings"] = mod

# Safe test env (no real secrets)
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("TICKET_MERCADO_PUBLICO", "TEST_TICKET_ONLY")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long")
os.environ.setdefault("DASHBOARD_PASS", "testpass-not-default")
os.environ.setdefault("FERNET_KEY", "")  # let crypto generate for tests
os.environ.setdefault("SMTP_HOST", "localhost")
os.environ.setdefault("SMTP_PORT", "1025")
os.environ.setdefault("SMTP_USER", "test@test.cl")
os.environ.setdefault("SMTP_PASSWORD", "pass")
os.environ.setdefault("SMTP_FROM", "test@test.cl")
os.environ.setdefault("SMTP_USE_TLS", "false")
os.environ.setdefault("API_RATE_PER_SECOND", "100")
os.environ.setdefault("API_RATE_PER_DAY", "10000")
os.environ.setdefault("API_ENRICH_RATE_PER_SECOND", "100")
os.environ.setdefault("API_MAX_RETRIES", "5")
os.environ.setdefault("API_CIRCUIT_BREAKER_THRESHOLD", "3")
os.environ.setdefault("API_CIRCUIT_BREAKER_PAUSE_SEC", "1")
