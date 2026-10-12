"""
app/scheduler.py — Scheduler multi-tenant con webhooks, digest y quota tracking.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from app.database import get_db
from app.models import (ReglaUsuario, AlertaGenerada, LicitacionSnapshot,
                        User, UserTicket, UserConfig, ApiQuotaLog)

logger = logging.getLogger(__name__)
_scheduler: Optional[BackgroundScheduler] = None


def _incrementar_quota(user_id: int, n: int = 1):
    fecha = datetime.utcnow().strftime("%Y-%m-%d")
    with get_db() as db:
        q = db.query(ApiQuotaLog).filter_by(user_id=user_id, fecha=fecha).first()
        if q:
            q.requests += n
        else:
            db.add(ApiQuotaLog(user_id=user_id, fecha=fecha, requests=n, limite=settings.API_RATE_PER_DAY))


def _quota_disponible(user_id: int) -> int:
    fecha = datetime.utcnow().strftime("%Y-%m-%d")
    with get_db() as db:
        q = db.query(ApiQuotaLog).filter_by(user_id=user_id, fecha=fecha).first()
        usados = q.requests if q else 0
        return max(0, settings.API_RATE_PER_DAY - usados)


def _sincronizar_tipo(tipo: str, ticket: str, user_id: int, dias: int = 1) -> List[Dict]:
    from app.api_client import MercadoPublicoClient, QuotaExhaustedException
    from app.normalizer import normalizar_licitacion, normalizar_oc

    disponible = _quota_disponible(user_id)
    if disponible <= 0:
        logger.warning("user=%s sin cuota API disponible", user_id)
        return []

    client = MercadoPublicoClient(ticket=ticket)
    entidades: List[Dict] = []
    try:
        if tipo == "licitacion":
            raw = client.buscar_licitaciones(dias=dias)
            entidades = [normalizar_licitacion(x) for x in raw]
        elif tipo == "orden_compra":
            raw = client.buscar_ordenes_compra(dias=dias)
            entidades = [normalizar_oc(x) for x in raw]
        else:
            logger.warning("tipo desconocido: %s", tipo)
    except QuotaExhaustedException as e:
        logger.error("Cuota agotada user=%s: %s", user_id, e)
    except Exception:
        logger.exception("Error sincronizando tipo=%s user=%s", tipo, user_id)

    # Persist snapshots (caché pública)
    with get_db() as db:
        for e in entidades:
            codigo = e.get("codigo")
            if not codigo:
                continue
            snap = db.query(LicitacionSnapshot).filter_by(codigo=codigo).first()
            if snap:
                snap.datos = e
                snap.estado = e.get("estado")
                snap.region = e.get("region")
                snap.monto_clp = e.get("monto_clp")
                if e.get("fecha_publicacion"):
                    try:
                        snap.fecha_publicacion = datetime.fromisoformat(str(e["fecha_publicacion"])[:10])
                    except Exception:
                        pass
            else:
                fp = None
                if e.get("fecha_publicacion"):
                    try:
                        fp = datetime.fromisoformat(str(e["fecha_publicacion"])[:10])
                    except Exception:
                        pass
                db.add(LicitacionSnapshot(
                    codigo=codigo, tipo=tipo, datos=e,
                    fecha_publicacion=fp, estado=e.get("estado"),
                    region=e.get("region"), monto_clp=e.get("monto_clp"),
                ))

    req_count = len(entidades)
    _incrementar_quota(user_id, req_count // 100 + 1)
    return entidades


def _evaluar_regla(regla: ReglaUsuario, entidades: List[Dict]) -> int:
    from app.filter_engine import evaluar_filtros

    nuevas = 0
    with get_db() as db:
        r = db.query(ReglaUsuario).filter_by(id=regla.id).first()
        if not r:
            return 0
        for e in entidades:
            if not evaluar_filtros(e, r.filtros or {}):
                continue
            entidad_id = e.get("codigo") or e.get("id") or ""
            if not entidad_id:
                continue
            existe = db.query(AlertaGenerada).filter_by(
                regla_id=r.id, entidad_id=str(entidad_id)
            ).first()
            if existe:
                continue
            db.add(AlertaGenerada(
                user_id=r.user_id,
                regla_id=r.id,
                entidad_id=str(entidad_id),
                tipo_entidad=r.tipo_entidad or e.get("tipo") or "licitacion",
                datos_resumen=e,
                enviado_email=False,
                mostrado_dashboard=True,
            ))
            nuevas += 1
        r.fecha_ultima_ejecucion = datetime.utcnow()
    return nuevas


def ejecutar_regla_manualmente(regla_id: int, ticket_override: Optional[str] = None) -> Dict:
    """Ejecuta una regla ya (sync API reciente + eval)."""
    with get_db() as db:
        regla = db.query(ReglaUsuario).filter_by(id=regla_id).first()
        if not regla:
            return {"error": "Regla no encontrada"}
        user_id = regla.user_id
        tipo = regla.tipo_entidad or "licitacion"
        # snapshot de campos necesarios antes de cerrar sesión
        regla_snapshot = ReglaUsuario(
            id=regla.id, user_id=regla.user_id, nombre_regla=regla.nombre_regla,
            activa=regla.activa, tipo_entidad=regla.tipo_entidad,
            filtros=dict(regla.filtros or {}), email_destino=regla.email_destino,
        )

    ticket = ticket_override
    if not ticket:
        with get_db() as db:
            ut = db.query(UserTicket).filter_by(user_id=user_id, activo=True).first()
            if not ut:
                return {"error": "Sin ticket de API configurado"}
            ticket = ut.get_ticket()

    entidades = _sincronizar_tipo(tipo, ticket, user_id, dias=3)

    # También evaluar contra snapshots ya en BD (últimos N días)
    cutoff = datetime.utcnow() - timedelta(days=settings.ALERT_DEDUP_DAYS)
    with get_db() as db:
        snaps = (
            db.query(LicitacionSnapshot)
            .filter(
                LicitacionSnapshot.tipo == tipo,
                LicitacionSnapshot.fecha_sincronizacion >= cutoff,
            )
            .limit(5000)
            .all()
        )
        extra = [s.datos for s in snaps if s.datos]

    # merge por codigo
    by_code = {}
    for e in entidades + extra:
        c = e.get("codigo")
        if c:
            by_code[c] = e
    merged = list(by_code.values())

    nuevas = _evaluar_regla(regla_snapshot, merged)
    return {
        "alertas_nuevas": nuevas,
        "entidades_evaluadas": len(merged),
        "sincronizadas": len(entidades),
    }


def ejecutar_ciclo_completo():
    """Ciclo diario: por cada usuario activo con ticket, sincroniza y evalúa reglas."""
    logger.info("Iniciando ciclo diario LiciEstado")
    with get_db() as db:
        users = db.query(User).filter_by(activo=True).all()
        user_ids = [u.id for u in users]

    for uid in user_ids:
        try:
            with get_db() as db:
                ut = db.query(UserTicket).filter_by(user_id=uid, activo=True).first()
                if not ut:
                    continue
                ticket = ut.get_ticket()
                reglas = db.query(ReglaUsuario).filter_by(user_id=uid, activa=True).all()
                reglas_data = [
                    (r.id, r.tipo_entidad or "licitacion",
                     dict(r.filtros or {}), r.email_destino, r.nombre_regla)
                    for r in reglas
                ]

            tipos = {t for _, t, *_ in reglas_data}
            cache_ent: Dict[str, List[Dict]] = {}
            for tipo in tipos:
                cache_ent[tipo] = _sincronizar_tipo(tipo, ticket, uid, dias=1)

            for rid, tipo, filtros, email, nombre in reglas_data:
                ents = cache_ent.get(tipo, [])
                fake = ReglaUsuario(
                    id=rid, user_id=uid, nombre_regla=nombre, activa=True,
                    tipo_entidad=tipo, filtros=filtros, email_destino=email,
                )
                n = _evaluar_regla(fake, ents)
                if n:
                    logger.info("user=%s regla=%s → %s alertas nuevas", uid, rid, n)
        except Exception:
            logger.exception("Error ciclo user=%s", uid)

    logger.info("Ciclo diario terminado")


def _enviar_digests():
    """Placeholder digest (email worker se encarga del envío real)."""
    if settings.ADMIN_EMAIL:
        logger.debug("Digest admin check OK")


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    tz = pytz.timezone(settings.TIMEZONE)
    _scheduler = BackgroundScheduler(timezone=tz)
    _scheduler.add_job(
        ejecutar_ciclo_completo,
        trigger=CronTrigger(hour=settings.SCHEDULER_HOUR, minute=settings.SCHEDULER_MINUTE, timezone=tz),
        id="ciclo_diario",
        replace_existing=True,
        name="Ciclo diario LiciEstado",
    )
    _scheduler.start()
    jobs = _scheduler.get_jobs()
    prox = jobs[0].next_run_time if jobs else None
    logger.info("Scheduler LiciEstado iniciado. Próxima: %s", prox)
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
