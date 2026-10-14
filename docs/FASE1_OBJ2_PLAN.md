# Fase 1 — Objetivo 2: PostgreSQL + Alembic

Rama: `fase1/objetivo2-postgres-alembic`

## Orden (Architect)

1. **Fixtures + tests** (3 variantes) — en curso
2. Alembic baseline + stamp en `init_db`
3. Consultas portables (`json_as_text`, `date_trunc_expr`) en analytics/routes/bid_analyzer
4. Docker: Postgres default, migraciones al arranque
5. `scripts/sqlite_to_postgres.py` (secuencias, conteos, dry-run)
6. CI dual + README (OneDrive, pg_dump)

## Criterio listo

- 3 variantes → head; BD real Rafa migra con conteos/hash iguales
- Analytics mismos números y etiquetas SQLite vs PG
- INSERT nuevo OK tras carga (secuencias)
- CI verde + `alembic check` limpio
