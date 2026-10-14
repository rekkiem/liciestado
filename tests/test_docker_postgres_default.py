"""Obj2: Docker defaults to PostgreSQL."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compose_default_database_url_is_postgres():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "postgresql+psycopg://" in text
    assert 'profiles: ["sqlite"]' in text
    assert "container_name: liciestado_db" in text


def test_entrypoint_runs_alembic_for_postgres():
    text = (ROOT / "scripts" / "docker_entrypoint.sh").read_text(encoding="utf-8")
    assert "alembic upgrade head" in text
    assert "postgresql" in text


def test_dockerfile_uses_entrypoint():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "docker_entrypoint.sh" in text
