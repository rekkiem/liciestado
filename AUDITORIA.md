# Auditoría LiciEstado — Fase 0 (en curso)

Rama: `fase0/saneamiento-critico`  
Estado: **no cerrada** — pendiente de aprobación del arquitecto y merge a `main`.

## Hallazgos → commits (post-revisión arquitecto rev3)

| ID | Descripción | Commit | Test | Resultado |
|----|-------------|--------|------|-----------|
| C2/A2 | models/scheduler from main + is_admin + es_pro relationship | 3335c18 | test_models_fase0.py | 7 passed |
| C1 | routes.py from origin/main + flash + /reglas + admin only | a602576 | (diff-only vs main) | APIs restauradas |
| C3/C4/C5/A1 | net_safety wiring, webhook worker, RuntimeError prod, delete restore_hotfix | 7aa5bda | test_webhook_validation + test_security_defaults | 29 passed total |

## Corregido

- C1: routes.py = origin/main + únicamente flash, `/reglas`, `/admin/users*`
- C2: AlertaGenerada idéntico a main (mostrado_dashboard, sin tipo_entidad); scheduler sin tipo_entidad
- C3: `validar_webhook_url` en auth_routes + revalidación en webhook_service (allow_redirects=False)
- C4: `iniciar_worker_webhook` restaurado vía main.py de origin/main
- C5: `check_insecure_defaults` en `create_app`; RuntimeError si production + defaults
- A1: `scripts/restore_hotfix.py` eliminado
- A2: `es_pro` sin get_db por acceso; timezone-aware; backref uselist=False
- A4: tests importan función real con mock getaddrinfo
- A5: `.github/workflows/ci.yml` (3.11/3.12, pytest, pyflakes)
- Bid analyzer: null-org guard en `_buscar_por_organismo` (justificado: evita 500)
- base.html: restaurado a origin/main

## No verificado en este entorno

- Tests de integración Flask client end-to-end (landing/registro/dashboard/api)
- Job CI real en GitHub Actions (workflow presente)
- Renombre visible en UI de "probabilidad de ganar" → "Índice de oportunidad (heurístico, no calibrado)" (aplicado en template)

## Regla de cierre

No se declara Fase 0 cerrada. El arquitecto revisa, aprueba y mergea a main.
