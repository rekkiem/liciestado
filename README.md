# LiciEstado 🔔

**Monitor multi-tenant de Mercado Público** — reglas de filtrado, alertas por email/webhook, analytics y Bid Analyzer.

Proyecto orientado a verticales **TI** y **Obras Públicas** (Salud en roadmap). Demo objetivo: noviembre 2026.

---

## ¿Qué hace?

| Característica | Detalle |
|---|---|
| 👥 Multi-tenant | Usuarios, planes free/pro, trial Pro, admin |
| 🎯 Motor de filtros | Región, monto, título/descripción, códigos de producto, estado (27 operadores) |
| ⏰ Scheduler diario | 06:00 America/Santiago (APScheduler) — sync API + eval reglas |
| 📧 Notificaciones | Email realtime o digest, webhooks SSRF-safe (`net_safety`) |
| 📊 Dashboard | Reglas, alertas, licitaciones, analytics, configuración de ticket |
| 📈 Analytics API | resumen, categorías, organismos, regional, temporal, diario |
| 🧮 Bid Analyzer | Análisis de precios (plan Pro / trial) |
| 🔐 Seguridad | Flask-Login, CSRF, bcrypt, tickets cifrados (Fernet), headers CSP |
| 🐳 Docker | Postgres por defecto: `docker compose up --build -d` |

---

## Fase 0 — Saneamiento critico ✅

Mergeado a `main` (PR #1, 2026-10-12).

---

## Inicio rápido

### 1. Prerrequisitos

- Python 3.11+ **o** Docker + Docker Compose
- Ticket de API de Mercado Público → [apis.mercadopublico.cl](https://apis.mercadopublico.cl/)
- SMTP para alertas por correo

### 2. Configuración

```bash
cd liciestado
cp .env.example .env
# Editar .env (FERNET_KEY, SECRET_KEY, SMTP_*)
```

### 3a. Docker (recomendado)

```bash
docker compose up --build -d          # app + Postgres (default)
docker compose logs -f app
docker compose --profile sqlite up -d # solo SQLite (sin servicio db)
```

- Dashboard: http://localhost:5000
- Entrypoint: espera PG + `alembic upgrade head` + `main.py`

### 3b. Python local

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
source .venv/bin/activate
pip install -r requirements.txt
$env:DATABASE_URL = "sqlite:///./mercadopublico.db"   # Windows PowerShell
python main.py
```

### Tests

```bash
pip install -r requirements.txt pytest
pytest tests/ -q
```

---

## Migración SQLite → PostgreSQL (Fase 1)

```bash
# 1. Destino con schema al día
DATABASE_URL=postgresql+psycopg://mp_user:mp_pass@localhost:5432/mp_alertas \
  python -c "from app.database import init_db; init_db()"

# 2. Dry-run (solo conteos)
python scripts/sqlite_to_postgres.py \
  --sqlite sqlite:///./mercadopublico.db \
  --postgres postgresql+psycopg://mp_user:mp_pass@localhost:5432/mp_alertas \
  --dry-run

# 3. Migrar
python scripts/sqlite_to_postgres.py \
  --sqlite sqlite:///./mercadopublico.db \
  --postgres postgresql+psycopg://mp_user:mp_pass@localhost:5432/mp_alertas
```

**OneDrive / Windows:** evita poner el volumen Postgres o el `.db` de trabajo dentro de una carpeta sincronizada (WAL/locks). Usa ruta local o `pg_dump`/`pg_restore` para backups.

---

## Comandos útiles

```bash
python main.py                  # Servidor + scheduler + workers
python main.py --once           # Un ciclo de sync/eval y sale
python scripts/enriquecer_bd.py --limite 30   # preferir ventana valle 22:00–07:00 CL
python -m alembic current
python -m alembic upgrade head
```

---

## Arquitectura (resumen)

```
main.py
  ├─ init_db()              # SQLite: create_all+migraciones+stamp; PG: alembic upgrade
  ├─ email / webhook workers
  ├─ APScheduler
  └─ Flask dashboard

app/
  api_client.py     # rate limit / 429 / circuit breaker
  db_dialect.py     # json_as_text, date_trunc_expr (SQLite+PG)
  analytics.py      # KPIs dialect-safe
  database.py       # engine, get_db, init_db Alembic-aware
  models.py
```

---

## Seguridad

- Passwords bcrypt; tickets Fernet
- CSRF; webhooks anti-SSRF (`net_safety`)
- Ticket nunca en logs (`redact_secrets`)

---

## Roadmap breve

- [x] Fase 0 — saneamiento critico
- [x] Fase 1 Obj1 — API resiliente 429
- [ ] Fase 1 Obj2 — Postgres + Alembic (en curso)
- [ ] Demo vertical TI + Obras
- [ ] Canales agente (Telegram prioritario)

---

## Licencia

MIT — Uso libre para proyectos comerciales y personales.
