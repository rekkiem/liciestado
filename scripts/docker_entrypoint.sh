#!/bin/sh
# Entrypoint: espera Postgres (si aplica), aplica migraciones Alembic, arranca la app.
set -e

echo "[entrypoint] DATABASE_URL=${DATABASE_URL:-unset}"

# Si es Postgres, esperar a que el puerto responda (compose healthcheck ya espera,
# pero por si el app arranca con URL externa).
case "${DATABASE_URL:-}" in
  postgresql*|postgres*)
    echo "[entrypoint] Esperando PostgreSQL…"
    python - <<'PY'
import os, time, sys
url = os.environ.get("DATABASE_URL", "")
try:
    import psycopg
    # Convertir sqlalchemy URL a libpq-ish
    dsn = url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
    for i in range(30):
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            print("[entrypoint] PostgreSQL listo")
            sys.exit(0)
        except Exception as e:
            print(f"[entrypoint] wait {i+1}/30: {e}")
            time.sleep(2)
    print("[entrypoint] TIMEOUT esperando PostgreSQL", file=sys.stderr)
    sys.exit(1)
except ImportError:
    print("[entrypoint] psycopg no disponible; se omite wait")
PY
    echo "[entrypoint] alembic upgrade head…"
    python -m alembic upgrade head || {
      echo "[entrypoint] alembic falló — init_db del main también intentará migrar"
    }
    ;;
  *)
    echo "[entrypoint] SQLite u otro motor — init_db manejará el schema"
    ;;
esac

exec python main.py "$@"
