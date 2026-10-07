from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # API Mercado Público
    TICKET_MERCADO_PUBLICO: str = ""
    API_BASE_URL: str = "https://api.mercadopublico.cl/servicios/v1"
    API_RATE_PER_SECOND: int = 5
    API_RATE_PER_DAY: int = 10_000

    # Base de datos
    DATABASE_URL: str = "sqlite:///./liciestado.db"

    # SMTP
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True

    # Multi-tenant: la contraseña de Basic Auth ya no se usa para el dashboard
    # Se mantiene para endpoints de admin (/api/status, etc.)
    DASHBOARD_USER: str = "admin"
    DASHBOARD_PASS: str = "admin"          # CAMBIAR en producción
    SECRET_KEY: str = "cambia-esto-en-produccion"  # CAMBIAR en producción (min 32 chars)

    # Cifrado Fernet para tickets de usuarios
    FERNET_KEY: str = ""

    ADMIN_EMAIL: Optional[str] = None
    SCHEDULER_HOUR: int = 6
    SCHEDULER_MINUTE: int = 0
    TIMEZONE: str = "America/Santiago"
    ALERT_DEDUP_DAYS: int = 30
    APP_BASE_URL: str = "http://localhost:5000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
