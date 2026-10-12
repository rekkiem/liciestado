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
| 🐳 Docker | `docker compose up --build -d` |

---

## Fase 0 — Saneamiento crítico ✅

Mergeado a `main` (PR #1, 2026-10-12). Cambios principales:

### Estabilidad y auth
- **DetachedInstanceError** resuelto: `expire_on_commit=False` + `expunge` de `User`/`UserConfig` en `cargar_usuario`
- Sesión Flask-Login usable fuera del `get_db()` (dashboard y `current_user.id`)

### Schema SQLite (migraciones en `init_db`)
- `alertas_generadas.tipo_entidad` (NOT NULL DEFAULT `'licitacion'`)
- `alertas_generadas.mostrado_dashboard`
- `api_quota_logs.creado_en` y `limite`
- `users.is_admin`, `user_configs.*` (digest, webhook, trial, etc.)
- Compatible con BDs creadas desde esquemas anteriores de `main`

### Scheduler y notificaciones
- Scheduler alineado con el diseño de producto: `encolar_alerta`, `encolar_digest`, `encolar_webhook`, resumen admin
- Respeta `notif_mode` (realtime / digest) y `ALERT_DEDUP_DAYS`
- `AlertaGenerada` inserta `tipo_entidad` desde la regla
- `ApiQuotaLog` inserta `limite=settings.API_RATE_PER_DAY`
- Entrypoints: `iniciar_scheduler` / `detener_scheduler`

### Dashboard y API
- Rutas restauradas: `/api/analytics/*`, `/api/status`, `/api/quota`, `/api/organismo/<nombre>`
- `/licitaciones/export.csv`, `/licitaciones/<id>/analizar` (+ `/json`)
- `/reglas`, `/admin/users*`
- Aliases en `AnalyticsEngine`: `resumen`, `por_categoria`, `por_organismo`, `por_region`, `temporal`, `diario`, `perfil_organismo`

### Tests y build
- `pytest.ini` → solo carpeta `tests/` (no ejecuta el legacy `test_mvp.py`)
- `.dockerignore` versionado (incluye `tests/` en la imagen)
- CI: pyflakes + pytest en 3.11 / 3.12

---

## Inicio rápido

### 1. Prerrequisitos

- Python 3.11+ **o** Docker + Docker Compose
- Ticket de API de Mercado Público → [apis.mercadopublico.cl](https://apis.mercadopublico.cl/)
- SMTP (Gmail App Password, SendGrid, etc.) para alertas por correo

### 2. Configuración

```bash
cd liciestado
cp .env.example .env
# Editar .env
```

Mínimo recomendado:

```env
SECRET_KEY=cambia_esto
DATABASE_URL=sqlite:////data/mercadopublico.db
# Ticket: por usuario en Configuración del dashboard (cifrado)
SMTP_HOST=smtp.gmail.com
SMTP_USER=tu@gmail.com
SMTP_PASSWORD=xxxx_xxxx_xxxx_xxxx
SMTP_FROM=tu@gmail.com
```

> El ticket de Mercado Público es **por usuario** (configuración en el dashboard). No hace falta ticket global salvo scripts legacy.

### 3a. Docker (recomendado)

```bash
docker compose up --build -d
docker compose logs -f app
```

- Dashboard: http://localhost:5000
- Landing: http://localhost:5000/landing

Registro / login multi-tenant en la UI. Crea tu usuario y pega el ticket en **Configuración**.

PostgreSQL opcional:

```bash
docker compose --profile postgres up -d
```

### 3b. Python local

```bash
python -m venv venv
# Windows: venv\Scripts\activate
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

### Tests

```bash
# En el contenedor
docker compose exec app pip install --user pytest
docker compose exec app python -m pytest tests/ -q

# En el host
pip install -r requirements.txt pytest
pytest tests/ -q
```

---

## Comandos útiles

```bash
python main.py                  # Servidor + scheduler + workers
python main.py --once           # Un ciclo de sync/eval y sale
python main.py --init-db        # Solo migraciones / create_all

# Enriquecimiento de snapshots (montos/región) — preferir horario valle
docker compose exec app python scripts/enriquecer_bd.py --limite 30
```

---

## Arquitectura (resumen)

```
main.py
  ├─ init_db()              # create_all + migraciones SQLite
  ├─ email worker           # cola de correos
  ├─ webhook worker         # cola webhooks (net_safety)
  ├─ APScheduler 06:00 CLT  # ciclo multi-tenant
  └─ Flask dashboard        # rutas autenticadas

app/
  auth.py           # registro, login, ticket cifrado, user_loader
  scheduler.py      # sync API → filtros → alertas → email/digest/webhook
  api_client.py     # Mercado Público + rate limit / backoff 429
  filter_engine.py  # operadores de reglas
  analytics.py      # KPIs dashboard
  bid_analyzer.py   # análisis de precios (Pro)
  net_safety.py     # validación URL webhook (anti-SSRF)
  database.py       # engine, get_db, migraciones
  models.py         # User, Regla, Alerta, Snapshot, Quota, …
```

---

## Modelo de planes

| Plan | Reglas | Bid Analyzer | Analytics |
|------|--------|--------------|-----------|
| Free | 3 | No | Básico |
| Pro / trial | Ilimitado* | Sí | Completo |
| Enterprise | Ilimitado | Sí | Completo |

\* `limite_reglas` vía `User.es_pro` (plan pro/enterprise o `trial_pro_hasta` activo).

---

## Seguridad

- Passwords con **bcrypt**
- Tickets API cifrados (Fernet / `app/crypto.py`)
- CSRF (Flask-WTF) en formularios
- Webhooks: bloqueo de IPs privadas / metadata cloud (`net_safety`)
- `check_insecure_defaults` en arranque (falla en production si hay defaults inseguros)
- Headers de seguridad en respuestas

---

## API interna (autenticada)

| Ruta | Uso |
|------|-----|
| `GET /api/analytics/resumen` | KPIs |
| `GET /api/analytics/categorias` | Top categorías |
| `GET /api/analytics/organismos` | Top organismos |
| `GET /api/analytics/regional` | Distribución regional |
| `GET /api/analytics/temporal` | Tendencia |
| `GET /api/analytics/diario` | Actividad diaria |
| `GET /api/status` | Estado app |
| `GET /api/quota` | Uso de cuota API del día |
| `GET /api/organismo/<nombre>` | Perfil organismo |
| `GET /licitaciones/export.csv` | Export CSV |
| `GET /licitaciones/<id>/analizar/json` | Bid Analyzer JSON |

---

## Troubleshooting

**500 en `/dashboard` (DetachedInstanceError)**  
Resuelto en Fase 0. Si reaparece: confirma `expire_on_commit=False` y `expunge` en `cargar_usuario`.

**`no such column: … tipo_entidad` / `creado_en` / `limite`**  
Reinicia la app (`init_db` migra). O verifica:

```bash
docker compose exec app python -c "from app.database import engine; from sqlalchemy import text; c=engine.connect(); print([r[1] for r in c.execute(text('PRAGMA table_info(alertas_generadas)')).fetchall()])"
```

**No llegan emails**  
1. `SMTP_*` en `.env`  
2. Gmail: App Password  
3. `docker compose logs -f app | grep -i email`  
4. Modo `notif_mode=digest` vs `realtime` en configuración de usuario  

**HTTP 429 de Mercado Público**  
El cliente reintenta con espera. Evita enrich masivo en horario punta; usa `--limite` bajo y ventanas 22:00–07:00 CLT.

**pytest: `tests/` not found en Docker**  
Actualiza `.dockerignore` del repo (no debe excluir `tests/`) y rebuild.

---

## Roadmap breve

- [x] Fase 0 — saneamiento crítico (merge PR #1)
- [ ] Demo vertical TI (reglas Netxia / equipos / servicios)
- [ ] Enrich controlado + menos 429 (backoff + ventanas)
- [ ] Canales agente gratuitos (Telegram prioritario)
- [ ] Vertical Salud

---

## Licencia

MIT — Uso libre para proyectos comerciales y personales.
