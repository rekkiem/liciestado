# Auditoría Técnica LiciEstado — actualizado Fase 0 (2026-10-07)

> Estado tras saneamiento crítico (Fase 0). Las falencias F1, F2, F5 (parcial), F13 (parcial) y F14 fueron atendidas.
> CSRF, rate-limit de auth y security headers **sí existen** en `app/security.py`.

# Auditoría Técnica LiciEstado — MVP vs Pitch ETMDay 2026

## 1. ALINEACIÓN ESTRATÉGICA

### ✅ Funcionalidades que EXISTEN en el MVP

| Funcionalidad | Estado | Observación |
| --- | --- | --- |
| Integración API Mercado Público v1 | ✅ Completo | iter_licitaciones, iter_ordenes_compra |
| Motor de filtros configurables | ✅ Completo | 11 operadores AND, JSON |
| Alertas por email | ✅ Completo | SMTP con queue thread-safe |
| Dashboard web multi-tenant | ✅ Completo | Flask-Login, user_id en todas las tablas |
| Scheduler automatizado | ✅ Completo | APScheduler, cron 6 AM |
| Base de datos histórica | ✅ Completo | licitaciones_snapshot compartida |
| Analytics básico | ✅ Completo | KPIs, temporal, regional, top organismos |
| Bid Analyzer Monte Carlo | ✅ Pro only | Sin datos reales de precio adjudicado |
| Cifrado de tickets API | ✅ Completo | Fernet AES-128 |
| Planes Free/Pro | ✅ Completo | Límite de reglas, gating de features |
| Export CSV licitaciones | ✅ Completo | 10K rows con filtros activos |

### ❌ Funcionalidades que el PITCH MENCIONA pero NO EXISTEN

| Brecha | Riesgo Pitch | Prioridad |
| --- | --- | --- |
| "Compras ágiles" — API no soporta tipo=CO | Overpromising ALTO | Fix inmediato en discurso |
| Notificaciones push / webhook | Implícito en "alertas inteligentes" | Alta |
| Análisis predictivo de patrones de compra | "copiloto comercial" | Media |
| Anticipar tendencias de compra | Visión 3-5 años | Baja (roadmap) |
| Integración Mercado Pago | Mencionado en pitch | Alta |
| Verificación de email en registro | Best practice SaaS | Alta |
| Resumen diario consolidado (digest) | UX esperado | Alta |
| Score/ranking de oportunidades visible | "identificar prioritarias" | Media |

---

## 2. REQUERIMIENTOS FUNCIONALES — GAP ANALYSIS

### Motor de filtros

* ✅ 11 operadores AND (región, monto, título, organismo, categoría, estado)
* ❌ Operadores OR entre reglas
* ❌ Filtro por fecha de publicación (solo fecha de cierre)
* ❌ Filtro por tipo de licitación (L1, LE, LP, etc.)
* ❌ Combinaciones negadas (NOT región)

### Sistema de alertas

* ✅ Email por alerta (real-time)
* ✅ Deduplicación por 30 días
* ❌ Digest diario consolidado (1 email/día con todas las alertas)
* ❌ Webhook / Slack / Teams
* ❌ Throttling configurable por usuario
* ❌ Priorización de alertas por score

### Seguridad

* ✅ Passwords con bcrypt
* ✅ Tickets cifrados con Fernet
* ✅ Flask-Login con sesiones
* ✅ CSRF protection (formularios)
* ✅ Rate limiting en endpoints de auth
* ❌ Verificación de email al registro
* ✅ Headers de seguridad (CSP, HSTS-ish, X-Frame-Options)

### API Mercado Público

* ✅ Rate limiting 5 req/s, 10K/día
* ✅ Retry con backoff exponencial
* ✅ Paginación completa
* ❌ Cuota compartida entre múltiples usuarios (cada uno tiene 10K, scheduler no las distribuye óptimamente)
* ❌ Cache TTL configurable (hardcoded 2h)
* ❌ Monitoreo de uso de cuota por usuario

### Multi-tenant

* ✅ user_id en reglas y alertas
* ✅ Queries filtradas por current_user.id
* ❌ Sin Row Level Security (SQLite no lo soporta; en PostgreSQL habría que añadirlo)
* ❌ Sin límite de rate por tenant en el scheduler

---

## 3. REQUERIMIENTOS NO FUNCIONALES

### Seguridad: 7/10

* CSRF, rate-limit auth y headers presentes
* Falta: verificación email, HMAC en webhooks

### Rendimiento: 7/10

* Índices en codigo, user_id, fecha_sincronizacion
* Falta: índice en datos JSON (SQLite no soporta), caché de consultas frecuentes

### Mantenibilidad: 7/10

* Suite pytest básica en tests/ (crypto + webhook)
* test_mvp.py marcado DEPRECATED
* Falta más cobertura y docs de API interna

### Escalabilidad: 7/10

* Arquitectura correcta para cientos de usuarios
* SQLite → PostgreSQL necesario antes de 50 usuarios concurrentes
* El scheduler bloqueante por usuario necesita async/queue para >20 usuarios

---

## 4. BRECHAS PARA "COPILOTO COMERCIAL"

### Data disponible para ML/Analytics

* ✅ Historial de licitaciones por organismo, región, categoría
* ✅ Patrones temporales (fecha publicación, cierre)
* ❌ Precios adjudicados (API no los entrega en endpoint de listado; sí en detalle por ítem)
* ❌ Número de oferentes por licitación (sí en Adjudicacion.NumeroOferentes del detalle)
* ❌ Historial de resultados por proveedor

### Quick wins de inteligencia con datos actuales

1. **Perfil de organismo** — frecuencia de compra, monto promedio, categorías preferidas
2. **Estacionalidad** — qué meses compra más cada organismo/categoría
3. **Score de oportunidad** — ya existe en bid_analyzer, mostrar en listado
4. **Alertas de tendencia** — "Este organismo compró 3 veces este rubro en los últimos 6 meses"
5. **Predicción próxima licitación** — basada en patrón histórico del organismo

---

## 5. MONETIZACIÓN

* ✅ Planes Free/Pro con gating de features
* ✅ Trial Pro 14 días (plan base free)
* ❌ Sin pasarela de pago (upgrade permanente a Pro bloqueado hasta integrar)
* ❌ Sin billing/facturación automatizada
* ❌ Sin métricas de conversión Free→Pro
* ✅ Exportación CSV (justifica plan Pro)
* ❌ Reportes PDF exportables (alto valor percibido)

---

## PRIORIDADES NUEVO RELEASE

### 🔴 CRÍTICO (seguridad/promesa pitch)

1. ~~CSRF protection~~ (ya existía)
2. ~~Rate limiting en endpoints auth~~ (ya existía)
3. Digest email diario (UX esperado por usuarios SaaS)
4. Cuota de API por usuario + monitoring

### 🟡 ALTO VALOR (diferenciación)

1. Webhook/notificación externa por regla (+ HMAC)
2. Perfil inteligente de organismos (frecuencia, estacionalidad)
3. Score visible en listado de alertas
4. Trial Pro 14 días automático para nuevos usuarios ✅
5. Onboarding wizard (3 pasos post-registro)

### 🟢 ROADMAP

1. PostgreSQL migration guide
2. Predicción próxima licitación por organismo
3. Integración Mercado Pago

## Estado Fase 0 (2026-10-07)

- F1: plan base free + trial 14d; upgrade permanente a Pro bloqueado hasta pagos.
- F2: crypto Fernet corregido (sin doble base64).
- F5: validación anti-SSRF en webhook_url (HTTPS + bloqueo hosts privados).
- F7: suite pytest en tests/ (7 tests verdes); test_mvp.py marcado DEPRECATED.
- F13: check_insecure_defaults() + comentarios en config.
- F14: CSRF/rate-limit/headers ya existían; AUDITORIA actualizado.
- F3/F4 (parcial): comentarios honestos; Bid Analyzer sigue siendo placeholder de ratios.
- Pendiente post-Fase0: HMAC webhooks, F6/F8/F10/F11/F12 → Fase 1.
