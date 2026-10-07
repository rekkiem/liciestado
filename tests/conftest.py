"""pytest fixtures for LiciEstado."""
import os
import sys
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
os.environ.setdefault("API_RATE_PER_DAY", "999999")
