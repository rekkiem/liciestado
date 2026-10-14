# Auditoría LiciEstado — Fase 0

Rama histórica: `fase0/saneamiento-critico`  
Estado: **mergeado a `main`** (PR #1, 2026-10-12, commit merge `9be41ed`).

## Checklist Arquitecto

| ID | Descripción | Estado |
|----|-------------|--------|
| C1 | routes API + `/reglas` + `/admin/users` | OK |
| C2 | models/scheduler; `tipo_entidad` en AlertaGenerada + migración | OK |
| C3 | `net_safety` en webhook | OK |
| C4 | worker webhook en `main.py` | OK |
| C5 | `check_insecure_defaults` | OK |
| A1 | sin `restore_hotfix.py` | OK |
| A2 | `es_pro` + `joinedload` / expunge en user_loader | OK |
| Notif | `encolar_alerta` / digest / webhook restaurados | OK |
| Session | `expire_on_commit=False` + DetachedInstance fix | OK |
| Quota | `api_quota_logs.limite` + `creado_en` migrados | OK |

## Validación post-merge

- Arranque Docker: scheduler 06:00, workers email/webhook, dashboard :5000
- `pytest tests/ -q` → 34 passed (entorno Docker con pytest instalado)
- GET dashboard / reglas / alertas / licitaciones / analytics → 200

## Referencia

Ver sección **Fase 0** en [README.md](README.md).

## Fase 1 / Objetivo 1 — notas post-verificación (2026-10-13)

Pendiente **Objetivo 4** (no bloquea merge Obj1):

- `iter_licitaciones` / `iter_ordenes_compra` devuelven lista vacía sin excepción tras un 429 agotado: una sync cortada aún puede parecer vacía. Marcar `sync_state=incompleto` en Obj4.
- Ítems que fallan o no traen región siguen "pendientes" indefinidamente → contadores de reintento en Obj4.
- Cuota diaria del rate limiter vive en memoria → persistir en BD en Obj4.
