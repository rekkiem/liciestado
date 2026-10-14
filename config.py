from pydantic import field_validator
from pydantic_settings import BaseSettings
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

    @field_validator("API_RATE_PER_DAY")
    @classmethod
    def _cap_daily_quota(cls, v: int) -> int:
        if v > 10_000:
            raise ValueError(
                "API_RATE_PER_DAY no puede superar 10000 (techo duro Mercado Público / producto)."
            )
        if v < 1:
            raise ValueError("API_RATE_PER_DAY debe ser >= 1")
        return v


settings = Settings()
