"""Obj4: registro de corridas de sync/enrich (completo|incompleto|error)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.database import get_db
from app.models import SyncRun

TZ_CL = ZoneInfo("America/Santiago")


def fecha_cl_hoy() -> str:
    return datetime.now(TZ_CL).strftime("%Y-%m-%d")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def start_sync_run(kind: str, fecha: Optional[str] = None) -> int:
    """Crea SyncRun en curso; devuelve id."""
    f = fecha or fecha_cl_hoy()
    with get_db() as db:
        row = SyncRun(
            kind=kind,
            fecha=f,
            estado="completo",
            started_at=_now(),
        )
        db.add(row)
        db.flush()
        return int(row.id)


def finish_sync_run(
    run_id: int,
    *,
    estado: str = "completo",
    motivo: Optional[str] = None,
    items_ok: int = 0,
    items_fail: int = 0,
) -> None:
    with get_db() as db:
        row = db.query(SyncRun).filter_by(id=run_id).first()
        if not row:
            return
        row.estado = estado
        row.motivo = motivo
        row.items_ok = items_ok
        row.items_fail = items_fail
        row.finished_at = _now()


def last_sync(kind: str, fecha: Optional[str] = None) -> Optional[SyncRun]:
    f = fecha or fecha_cl_hoy()
    with get_db() as db:
        return (
            db.query(SyncRun)
            .filter_by(kind=kind, fecha=f)
            .order_by(SyncRun.id.desc())
            .first()
        )
