try:
    from pydantic_settings import BaseSettings
except ImportError:  # pragma: no cover
    from pydantic import BaseModel as BaseSettings  # type: ignore

from typing import Optional


class Settings(BaseSettings):
    TICKET_MERCADO_PUBLICO: str = ""
    API_BASE_URL: str = "https://api.mercadopublico.cl/servicios/v1"
    # Ritmo general (sync diario, dashboard on-demand)
    API_RATE_PER_SECOND: float = 5.0
    API_RATE_PER_DAY: int = 10_000
    # Ritmo de enriquecimiento (más conservador)
    API_ENRICH_RATE_PER_SECOND: float = 2.0
    API_MAX_RETRIES: int = 5
    # Tras N ciclos de 429 agotados seguidos, pausar el cliente
    API_CIRCUIT_BREAKER_THRESHOLD: int = 3
    API_CIRCUIT_BREAKER_PAUSE_SEC: float = 900.0  # 15 min

    DATABASE_URL: str = "sqlite:///./mercadopublico.db"

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True

    # Multi-tenant: la contraseña de Basic Auth ya no se usa para el dashboard
    # Se mantiene para endpoints de admin (/api/status, etc.)
    DASHBOARD_USER: str = "admin"
    DASHBOARD_PASS: str = "admin"
    SECRET_KEY: str = "cambia-esto-en-produccion"

    # Cifrado Fernet para tickets de usuarios
    FERNET_KEY: str = ""

    ADMIN_EMAIL: Optional[str] = None
    SCHEDULER_HOUR: int = 6
    SCHEDULER_MINUTE: int = 0
    TIMEZONE: str = "America/Santiago"
    ALERT_DEDUP_DAYS: int = 30
    APP_BASE_URL: str = "http://localhost:5000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def _load_settings() -> Settings:
    try:
        return Settings()
    except Exception:
        # Fallback si pydantic-settings no lee env (BaseModel puro)
        import os
        kwargs = {}
        mapping = {
            "TICKET_MERCADO_PUBLICO": str,
            "API_BASE_URL": str,
            "API_RATE_PER_SECOND": float,
            "API_RATE_PER_DAY": int,
            "API_ENRICH_RATE_PER_SECOND": float,
            "API_MAX_RETRIES": int,
            "API_CIRCUIT_BREAKER_THRESHOLD": int,
            "API_CIRCUIT_BREAKER_PAUSE_SEC": float,
            "DATABASE_URL": str,
            "SECRET_KEY": str,
            "DASHBOARD_PASS": str,
        }
        for key, caster in mapping.items():
            if key in os.environ:
                try:
                    kwargs[key] = caster(os.environ[key])
                except Exception:
                    pass
        return Settings(**kwargs)


settings = _load_settings()
