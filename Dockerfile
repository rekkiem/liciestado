# ── Stage 1: Builder ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="tu@email.com"
LABEL description="MP Alertas — Monitor de Mercado Público con alertas por email"
LABEL version="1.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    DATABASE_URL=postgresql+psycopg://mp_user:mp_pass@db:5432/mp_alertas \
    TZ=America/Santiago

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl tzdata && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1001 appuser

COPY --from=builder /install /usr/local

WORKDIR /app

COPY --chown=appuser:appuser . .

RUN mkdir -p /data /app/logs && \
    chown -R appuser:appuser /data /app/logs

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f -u "${DASHBOARD_USER:-admin}:${DASHBOARD_PASS:-admin}" \
        http://localhost:${PORT:-5000}/ || exit 1

EXPOSE ${PORT:-5000}

# Entrypoint: normalizar CRLF (Windows checkout) + wait PG + alembic + main
USER root
RUN sed -i 's/\r$//' /app/scripts/docker_entrypoint.sh && \
    chmod +x /app/scripts/docker_entrypoint.sh
USER appuser

# Usar /bin/sh evita "no such file" cuando el shebang llega con \r
ENTRYPOINT ["/bin/sh", "/app/scripts/docker_entrypoint.sh"]
CMD []
