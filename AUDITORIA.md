# Auditoría LiciEstado — Fase 0 (en curso)

Rama: `fase0/saneamiento-critico`  
Estado: **no cerrada** — pendiente de aprobación del arquitecto y merge a `main`.

## Corregido en esta rama (post-revisión arquitecto)

| ID | Descripción | Estado |
|----|-------------|--------|
| C1 | routes.py desde main + `/reglas` + `/admin/users` (APIs analytics/export restauradas) | OK |
| C2 | models/scheduler/config alineados a main; solo `is_admin` + `es_pro` trial | OK |
| C3 | `app/net_safety.validar_webhook_url` anti-SSRF real + revalidación al enviar | OK |
| C4 | Worker de webhooks restaurado en `main.py` | OK |
| C5 | `check_insecure_defaults` en `create_app`; RuntimeError en production | OK |
| A1 | Eliminado `scripts/restore_hotfix.py` (stub de deprecación) | OK |
| A2 | `User.es_pro` sin `get_db` por acceso; timezone-aware | OK |
| A4 | Tests importan la función real (mock getaddrinfo) | OK |
| A5 | `.github/workflows/ci.yml` | OK |
| F2 | crypto Fernet | OK (no tocado en esta pasada) |
| F1 | `/upgrade/pro` no cambia plan | OK (según revisión previa) |

## Pendiente / no verificado aquí

- Tests de integración Flask client end-to-end (landing→registro→dashboard) — ejecutar en CI/local.
- Calibración del Bid Analyzer (solo renombre de etiqueta heurística).
- Enriquecimiento de montos/región en snapshots (dato, no esquema).

## Regresiones evitadas

- No se declara Fase 0 cerrada hasta merge aprobado.
- No se usan commits intermedios ni URLs externas para restaurar código; línea base = `origin/main`.
