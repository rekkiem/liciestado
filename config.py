"""
config.py — Configuración centralizada via variables de entorno.
"""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Base de datos
    DATABASE_URL: str = "sqlite:///./mercadopublico.db"

    # Mercado Público
    MP_TICKET: str = ""
    API_RATE_PER_DAY: int = 50000

    # Scheduler
    SCHEDULER_HOUR: int = 6
    SCHEDULER_MINUTE: int = 0
    TIMEZONE: str = "America/Santiago"

    # Auth dashboard legacy / defaults
    DASHBOARD_USER: str = "admin"
    DASHBOARD_PASS: str = "admin"
    SECRET_KEY: str = "cambia-esto-en-produccion"

    # Email
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM: str = ""
    ADMIN_EMAIL: str = ""

    # Alertas
    ALERT_DEDUP_DAYS: int = 7

    # Crypto
    FERNET_KEY: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
