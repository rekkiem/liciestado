# Fase 1 — Objetivo 2: PostgreSQL + Alembic

Rama: `fase1/objetivo2-postgres-alembic`

## Orden (Architect) — estado

1. **Fixtures + tests** (3 variantes) — ✅
2. Alembic baseline + stamp en `init_db` — ✅ (`001_baseline`)
3. Consultas portables (`json_as_text`, `date_trunc_expr`) — ✅ analytics / routes / bid_analyzer
4. Docker: Postgres default, migraciones al arranque — ✅ entrypoint + compose
5. `scripts/sqlite_to_postgres.py` — ✅ dry-run, setval, FK order
6. CI dual + README — ✅ matrix 3.11/3.12 × sqlite/postgres

## Criterio listo

- [x] Baseline Alembic alineado a models
- [x] init_db: SQLite stamp / PG upgrade
- [x] Helpers dialect-safe
- [x] Docker Postgres default
- [x] Migrador SQLite→PG
- [x] CI matrix
- [ ] Validación Architect + merge a main
- [ ] (Etapa final) batería extendida / fixtures→head en PG real
