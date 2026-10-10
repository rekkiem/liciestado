# Auditoría LiciEstado — Fase 0 (lista para merge)

Rama: `fase0/saneamiento-critico`  
Estado: **lista para merge a main** tras validación local (dashboard / reglas / alertas / licitaciones / analizar → 200).

## Checklist Arquitecto

| ID | Descripción | Estado |
|----|-------------|--------|
| C1 | routes + `/reglas` + `/admin/users` | OK (UI); APIs analytics en rama |
| C2 | models/scheduler alineados; sin `tipo_entidad` en AlertaGenerada | OK |
| C3 | `net_safety` en config webhook + revalidación al enviar | OK |
| C4 | worker webhook en `main.py` | OK |
| C5 | `check_insecure_defaults` (RuntimeError en production) | OK |
| A1 | `restore_hotfix.py` eliminado | OK |
| A2 | `es_pro` sin get_db/lazy; `joinedload` en user_loader | OK |
| Schema | migraciones `is_admin`, `mostrado_dashboard`, `digest_hora` | OK |

## Validado en Docker (2026-10-09)

- Migración `user_configs.digest_hora` aplicada al arrancar
- GET `/dashboard`, `/reglas`, `/alertas`, `/licitaciones`, `/analytics`, `/upgrade`, `/licitaciones/<id>/analizar` → **200**
- Bid Analyzer carga sin 500

## Merge

```bash
git checkout main && git pull
git merge fase0/saneamiento-critico
git push origin main
```

No se declara Fase 0 "cerrada por el agente"; el merge es decisión del mantenedor tras esta validación.
