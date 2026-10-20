"""Obj6: payload de /api/status (outbox, sync, cuota, scheduler)."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import jsonify
from flask_login import current_user
from sqlalchemy import func

from app.database import get_db
from app.models import AlertaGenerada, LicitacionSnapshot


def build_status_response():
    """JSON de estado real para GET /api/status (requiere usuario autenticado)."""
    from app.scheduler import _scheduler
    from app.models import ApiQuotaDaily, NotificationOutbox, SyncRun
    from app.sync_state import fecha_cl_hoy

    uid = current_user.id
    job = None
    if _scheduler:
        j = _scheduler.get_job("ciclo_diario")
        job = str(j.next_run_time) if j and j.next_run_time else None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    fecha = fecha_cl_hoy()

    with get_db() as db:
        n_lic = db.query(func.count(LicitacionSnapshot.id)).scalar() or 0
        n_alertas = (
            db.query(func.count(AlertaGenerada.id))
            .filter(AlertaGenerada.user_id == uid)
            .scalar()
            or 0
        )

        pend = (
            db.query(func.count(NotificationOutbox.id))
            .filter(NotificationOutbox.estado.in_(("pendiente", "procesando")))
            .scalar()
            or 0
        )
        fail = (
            db.query(func.count(NotificationOutbox.id))
            .filter(NotificationOutbox.estado == "fallido")
            .scalar()
            or 0
        )
        oldest = (
            db.query(NotificationOutbox.created_at)
            .filter(NotificationOutbox.estado.in_(("pendiente", "procesando")))
            .order_by(NotificationOutbox.created_at.asc())
            .first()
        )
        oldest_age_s = None
        if oldest and oldest[0]:
            oldest_age_s = max(0, int((now - oldest[0]).total_seconds()))

        last_runs = db.query(SyncRun).order_by(SyncRun.id.desc()).limit(5).all()
        sync = [
            {
                "kind": r.kind,
                "fecha": r.fecha,
                "estado": r.estado,
                "motivo": (r.motivo or "")[:200] or None,
                "items_ok": r.items_ok,
                "items_fail": r.items_fail,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in last_runs
        ]
        incompletos = (
            db.query(func.count(SyncRun.id))
            .filter(SyncRun.estado == "incompleto")
            .scalar()
            or 0
        )

        qrow = db.query(ApiQuotaDaily).filter_by(fecha=fecha).first()
        from config import settings

        limite = int(getattr(settings, "API_RATE_PER_DAY", 10_000) or 10_000)
        usados = qrow.requests if qrow else 0
        if qrow and qrow.limite:
            limite = qrow.limite

    return jsonify(
        {
            "ok": True,
            "user_id": uid,
            "db": {"licitaciones_snapshot": n_lic, "alertas_usuario": n_alertas},
            "scheduler": {"proxima_ejecucion": job},
            "outbox": {
                "pendientes": pend,
                "fallidos": fail,
                "edad_mas_viejo_seg": oldest_age_s,
            },
            "sync": {"runs_recientes": sync, "incompletos_total": incompletos},
            "cuota": {
                "fecha": fecha,
                "usados": usados,
                "limite": limite,
                "restantes": max(0, limite - usados),
            },
        }
    )
