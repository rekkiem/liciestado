"""
app/scheduler.py — Scheduler multi-tenant con webhooks, digest y quota tracking.
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import settings
from app.database import get_db
from app.models import (ReglaUsuario, AlertaGenerada, LicitacionSnapshot,
                        User, UserTicket, UserConfig, ApiQuotaLog)
from app.normalizer import normalizar_entidad, datos_resumen
from app.filter_engine import evaluar_regla
from app.email_service import encolar_alerta, encolar_resumen_admin, encolar_digest

logger = logging.getLogger(__name__)
_scheduler: Optional[BackgroundScheduler] = None


def _incrementar_quota(user_id: int, n: int = 1):
    fecha = datetime.utcnow().strftime("%Y-%m-%d")
    with get_db() as db:
        q = db.query(ApiQuotaLog).filter_by(user_id=user_id, fecha=fecha).first()
        if q:
            q.requests += n
        else:
            db.add(ApiQuotaLog(user_id=user_id, fecha=fecha, requests=n))


def _quota_disponible(user_id: int) -> int:
    fecha = datetime.utcnow().strftime("%Y-%m-%d")
    with get_db() as db:
        q = db.query(ApiQuotaLog).filter_by(user_id=user_id, fecha=fecha).first()
        usados = q.requests if q else 0
        return max(0, settings.API_RATE_PER_DAY - usados)


def _sincronizar_tipo(tipo: str, ticket: str, user_id: int, dias: int = 1) -> List[Dict]:
    from app.api_client import MercadoPublicoClient, QuotaExhaustedException

    if tipo == "compra_agil":
        logger.warning("[SYNC] compra_agil omitida — API no soporta tipo=CO")
        return []

    MAX_POR_TIPO = {"licitacion": 50_000, "orden_compra": 20_000}
    max_reg = MAX_POR_TIPO.get(tipo, 5_000)

    disponible = _quota_disponible(user_id)
    if disponible < 10:
        logger.warning("[SYNC] user_id=%d sin cuota disponible (%d restantes)", user_id, disponible)
        return []

    client = MercadoPublicoClient(ticket=ticket)
    fecha_api = client.to_api_date(datetime.now() - timedelta(days=dias))
    iterator = (client.iter_licitaciones(fecha_desde=fecha_api)
                if tipo == "licitacion"
                else client.iter_ordenes_compra(fecha_desde=fecha_api))

    logger.info("[SYNC user=%d] Tipo=%s desde %s", user_id, tipo, fecha_api)
    entidades_norm: List[Dict] = []
    seen: set = set()
    req_count = 0

    try:
        for raw in iterator:
            entidad = normalizar_entidad(raw, tipo)
            if not entidad:
                continue
            codigo = entidad.get("codigo", "")
            if not codigo or codigo in seen:
                continue
            seen.add(codigo)
            entidades_norm.append(entidad)
            req_count += 1
            if req_count >= min(max_reg, disponible):
                break
    except QuotaExhaustedException:
        logger.error("[SYNC] Cuota API agotada para user_id=%d", user_id)

    _incrementar_quota(user_id, req_count // 100 + 1)

    if entidades_norm:
        nuevos = actualizados = 0
        with get_db() as db:
            codigos = [e["codigo"] for e in entidades_norm]
            existentes = {r.codigo for r in db.query(LicitacionSnapshot.codigo).filter(
                LicitacionSnapshot.codigo.in_(codigos)).all()}
            for entidad in entidades_norm:
                codigo = entidad["codigo"]
                fp = None
                if entidad.get("fecha_publicacion"):
                    try:
                        fp = datetime.strptime(entidad["fecha_publicacion"], "%Y-%m-%d")
                    except Exception:
                        pass
                if codigo in existentes:
                    db.query(LicitacionSnapshot).filter_by(codigo=codigo).update({
                        "datos": entidad, "region": entidad.get("region"),
                        "monto_clp": entidad.get("monto_clp"),
                        "estado": entidad.get("estado"), "fecha_publicacion": fp,
                    })
                    actualizados += 1
                else:
                    db.add(LicitacionSnapshot(
                        codigo=codigo, tipo=tipo, datos=entidad,
                        region=entidad.get("region"), monto_clp=entidad.get("monto_clp"),
                        estado=entidad.get("estado"), fecha_publicacion=fp,
                    ))
                    existentes.add(codigo)
                    nuevos += 1
        logger.info("[SYNC user=%d] %s → %d nuevos, %d actualizados", user_id, tipo, nuevos, actualizados)

    return entidades_norm


def _evaluar_reglas_sobre_entidades(reglas, entidades, user_id, notif_mode="digest") -> Dict:
    from app.webhook_service import encolar_webhook
    alertas_nuevas = 0
    cutoff = datetime.utcnow() - timedelta(days=settings.ALERT_DEDUP_DAYS)

    webhook_url = None
    with get_db() as db:
        cfg = db.query(UserConfig).filter_by(user_id=user_id).first()
        if cfg and cfg.webhook_activo and cfg.webhook_url:
            webhook_url = cfg.webhook_url
        notif_mode = cfg.notif_mode if cfg else "digest"

    with get_db() as db:
        for regla in reglas:
            coincidencias = [e for e in entidades if evaluar_regla(regla, e)]
            if not coincidencias:
                continue

            ya_alertados = {r.entidad_id for r in db.query(AlertaGenerada.entidad_id)
                            .filter(AlertaGenerada.regla_id == regla.id,
                                    AlertaGenerada.fecha_alerta >= cutoff).all()}

            nuevas_alerta = []
            for entidad in coincidencias:
                eid = entidad.get("codigo", "")
                if not eid or eid in ya_alertados:
                    continue
                resumen = datos_resumen(entidad)
                alerta = AlertaGenerada(
                    user_id=user_id, regla_id=regla.id, entidad_id=eid,
                    tipo_entidad=getattr(regla, "tipo_entidad", None) or "licitacion",
                    datos_resumen=resumen, enviado_email=False,
                )
                db.add(alerta)
                ya_alertados.add(eid)
                nuevas_alerta.append(resumen)
                alertas_nuevas += 1

                if webhook_url:
                    db.flush()
                    encolar_webhook(webhook_url, regla.nombre_regla, resumen, user_id)

                if notif_mode == "realtime":
                    encolar_alerta(regla.nombre_regla, resumen, regla.emails_lista)

            regla.fecha_ultima_ejecucion = datetime.utcnow()

    return {"alertas_nuevas": alertas_nuevas}


def _ciclo_usuario(user: User, ticket: str) -> Dict:
    logger.info("[USER %d] Ciclo para %s", user.id, user.email)

    with get_db() as db:
        reglas = db.query(ReglaUsuario).filter_by(user_id=user.id, activa=True).all()
        cfg    = db.query(UserConfig).filter_by(user_id=user.id).first()
        notif_mode = cfg.notif_mode if cfg else "digest"

    if not reglas:
        return {"reglas_evaluadas": 0, "alertas_nuevas": 0}

    tipos = {r.tipo_entidad for r in reglas} - {"compra_agil"}
    todas: Dict[str, List[Dict]] = {}
    cutoff_sinc = datetime.utcnow() - timedelta(hours=2)

    for tipo in tipos:
        with get_db() as db:
            snaps = db.query(LicitacionSnapshot).filter(
                LicitacionSnapshot.tipo == tipo,
                LicitacionSnapshot.fecha_sincronizacion >= cutoff_sinc,
            ).all()
            if snaps:
                logger.info("[USER %d] Reutilizando %d del snapshot (< 2h)", user.id, len(snaps))
                todas[tipo] = [s.datos for s in snaps if s.datos]
            else:
                todas[tipo] = _sincronizar_tipo(tipo, ticket, user.id, dias=1)

    total_alertas = 0
    for tipo, entidades in todas.items():
        reglas_tipo = [r for r in reglas if r.tipo_entidad == tipo]
        if not reglas_tipo or not entidades:
            continue
        stats = _evaluar_reglas_sobre_entidades(reglas_tipo, entidades, user.id, notif_mode)
        total_alertas += stats["alertas_nuevas"]

    if notif_mode == "digest" and total_alertas > 0:
        cutoff_hoy = datetime.utcnow() - timedelta(hours=1)
        with get_db() as db:
            alertas_hoy = db.query(AlertaGenerada).filter(
                AlertaGenerada.user_id == user.id,
                AlertaGenerada.fecha_alerta >= cutoff_hoy,
                AlertaGenerada.enviado_email == False,
            ).all()
            email_user = user.email
            resumen_alertas = [{"regla": a.regla.nombre_regla if a.regla else "—",
                                 "datos": a.datos_resumen} for a in alertas_hoy]
            ids_actualizar = [a.id for a in alertas_hoy]

        if resumen_alertas:
            encolar_digest(email_user, resumen_alertas)
            with get_db() as db:
                db.query(AlertaGenerada).filter(
                    AlertaGenerada.id.in_(ids_actualizar)
                ).update({"enviado_email": True}, synchronize_session=False)

    logger.info("[USER %d] Ciclo OK: %d alertas nuevas", user.id, total_alertas)
    return {"reglas_evaluadas": len(reglas), "alertas_nuevas": total_alertas}


def ejecutar_ciclo_completo() -> Dict:
    logger.info("=" * 60)
    logger.info("INICIO CICLO LICIESTADO: %s", datetime.utcnow().isoformat())
    logger.info("=" * 60)

    from app.crypto import descifrar_ticket
    with get_db() as db:
        usuarios = (db.query(User).join(UserTicket, UserTicket.user_id == User.id)
                    .filter(User.activo == True, UserTicket.activo == True).all())
        user_tickets = {}
        for u in usuarios:
            try:
                ut = db.query(UserTicket).filter_by(user_id=u.id, activo=True).first()
                if ut:
                    user_tickets[u.id] = descifrar_ticket(ut.ticket_cifrado)
            except Exception as e:
                logger.error("Error ticket user_id=%d: %s", u.id, e)

    total_alertas = errores = 0
    for user in usuarios:
        ticket = user_tickets.get(user.id)
        if not ticket:
            continue
        try:
            stats = _ciclo_usuario(user, ticket)
            total_alertas += stats.get("alertas_nuevas", 0)
        except Exception as e:
            logger.exception("Error ciclo user_id=%d: %s", user.id, e)
            errores += 1

    resumen = {"usuarios_procesados": len(usuarios), "alertas_nuevas": total_alertas,
               "errores": errores, "tipos_consultados": ["licitacion", "orden_compra"]}
    logger.info("CICLO LICIESTADO COMPLETADO: %s", resumen)

    if settings.ADMIN_EMAIL:
        encolar_resumen_admin(resumen)

    return resumen


def ejecutar_regla_manualmente(regla_id: int, ticket_override: Optional[str] = None) -> Dict:
    from app.auth import obtener_ticket_plano
    with get_db() as db:
        regla = db.query(ReglaUsuario).filter_by(id=regla_id).first()
        if not regla:
            return {"error": "Regla no encontrada"}
        user_id = regla.user_id
        tipo    = regla.tipo_entidad
        logger.info("Manual: regla '%s' (id=%d)", regla.nombre_regla, regla_id)

    ticket = ticket_override or (obtener_ticket_plano(user_id) if user_id else None)
    if not ticket:
        return {"error": "Sin ticket de API"}

    cutoff = datetime.utcnow() - timedelta(hours=2)
    with get_db() as db:
        snaps = db.query(LicitacionSnapshot).filter(
            LicitacionSnapshot.tipo == tipo,
            LicitacionSnapshot.fecha_sincronizacion >= cutoff,
        ).all()
        entidades = [s.datos for s in snaps if s.datos]

    if not entidades:
        entidades = _sincronizar_tipo(tipo, ticket, user_id or 0, dias=1)

    with get_db() as db:
        regla = db.query(ReglaUsuario).filter_by(id=regla_id).first()
        stats = _evaluar_reglas_sobre_entidades([regla], entidades, user_id or 0)

    return {**stats, "entidades_evaluadas": len(entidades)}


def iniciar_scheduler() -> BackgroundScheduler:
    global _scheduler
    tz = pytz.timezone(settings.TIMEZONE)
    _scheduler = BackgroundScheduler(timezone=tz)
    _scheduler.add_job(func=ejecutar_ciclo_completo,
        trigger=CronTrigger(hour=settings.SCHEDULER_HOUR, minute=settings.SCHEDULER_MINUTE, timezone=tz),
        id="ciclo_diario", name="Ciclo diario LiciEstado",
        replace_existing=True, misfire_grace_time=3600)
    _scheduler.start()
    logger.info("Scheduler LiciEstado iniciado. Próxima: %s",
                _scheduler.get_job("ciclo_diario").next_run_time)
    return _scheduler


def detener_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
