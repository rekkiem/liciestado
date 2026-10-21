#!/usr/bin/env python3
"""
scripts/enriquecer_bd.py
Enriquece snapshots sin región/monto con detalle API.
Obj4: enrich_attempts con tope, sync_run incompleto al cortar por 429/cuota.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("enriquecer")

from app.database import init_db, get_db
from app.models import LicitacionSnapshot
from app.sync_state import start_sync_run, finish_sync_run, fecha_cl_hoy
from app.api_client import (
    make_enrich_client,
    QuotaExhaustedException,
    RateLimitedException,
    ApiClientException,
    redact_secrets,
)
from app.normalizer import normalizar_licitacion, normalizar_orden_compra
from config import settings

G = "\033[92m"
Y = "\033[93m"
C = "\033[96m"
R = "\033[91m"
B = "\033[1m"
NC = "\033[0m"

TZ_CL = ZoneInfo("America/Santiago")
VALLE_INICIO = 22
VALLE_FIN = 7


def _en_ventana_valle(now: datetime | None = None) -> bool:
    now = now or datetime.now(TZ_CL)
    h = now.hour
    return h >= VALLE_INICIO or h < VALLE_FIN


def run(
    limite: int | None,
    dry_run: bool,
    solo_sin_region: bool,
    lote: int,
    *,
    force: bool = False,
) -> int:
    """
    Returns exit code:
      0 = completado (o dry-run)
      2 = incompleto (cortado por cuota / rate limit)
      1 = error inesperado / rechazado por política de ventana
    """
    init_db()
    client = make_enrich_client()
    rate = getattr(settings, "API_ENRICH_RATE_PER_SECOND", 2.0)
    max_attempts = int(getattr(settings, "MAX_ENRICH_ATTEMPTS", 5))

    with get_db() as db:
        q = db.query(LicitacionSnapshot)
        if solo_sin_region:
            q = q.filter(LicitacionSnapshot.region.is_(None))
        q = q.filter(LicitacionSnapshot.enrich_attempts < max_attempts)
        total_pendiente = q.count()
        pendientes = q.limit(limite).all() if limite is not None else q.all()
        codigos = [(s.id, s.codigo, s.tipo) for s in pendientes]

    print(f"\n{B}Enriquecer BD — fetch detalle por código{NC}")
    print(f"  Pendientes : {total_pendiente:,} snapshots sin región/monto")
    print(f"  A procesar : {len(codigos):,}")
    print(f"  Lote       : {lote}")
    print(f"  Ritmo      : {rate} req/s (techo diario {settings.API_RATE_PER_DAY:,})")
    print(f"  Modo       : {'DRY RUN' if dry_run else 'ESCRITURA'}")

    now_cl = datetime.now(TZ_CL)
    en_valle = _en_ventana_valle(now_cl)
    if en_valle:
        print(f"  {G}Ventana valle OK ({now_cl.strftime('%H:%M %Z')}){NC}")
    else:
        print(
            f"  {Y}Aviso: fuera de ventana valle (22:00–07:00 CL). "
            f"Ahora {now_cl.strftime('%H:%M %Z')}.{NC}"
        )
        if len(codigos) > 50 and not force:
            print(
                f"  {R}Rechazado: >50 ítems fuera de valle. "
                f"Usa --limite 50 (o menos) o --force.{NC}\n"
            )
            return 1
        if force:
            print(f"  {Y}--force activo: se continúa fuera de valle.{NC}")
    print()

    if dry_run:
        est_sec = len(codigos) / max(rate, 0.1)
        print(f"  {Y}DRY RUN: se necesitan {len(codigos)} llamadas a la API.{NC}")
        print(f"  Tiempo estimado: ~{int(est_sec // 60)}m {int(est_sec % 60)}s @ {rate} req/s\n")
        return 0

    if not codigos:
        print(f"  {G}Nada pendiente.{NC}\n")
        return 0

    ok = err = omit = 0
    incompleto = False
    motivo_corte = ""
    run_id = start_sync_run("enrich", fecha_cl_hoy())

    for i, (snap_id, codigo, tipo) in enumerate(codigos, 1):
        try:
            if tipo == "licitacion":
                detalle = client.get_licitacion_detalle(codigo)
                if not detalle:
                    omit += 1
                    with get_db() as db:
                        db.query(LicitacionSnapshot).filter_by(id=snap_id).update(
                            {
                                "enrich_attempts": LicitacionSnapshot.enrich_attempts + 1,
                                "last_enrich_error": "detalle_vacio",
                            },
                            synchronize_session=False,
                        )
                    continue
                norm = normalizar_licitacion(detalle)
            else:
                data = client._get("publico/ordenesdecompra.json", {"codigo": codigo})
                listado = data.get("Listado") or []
                if not listado:
                    omit += 1
                    with get_db() as db:
                        db.query(LicitacionSnapshot).filter_by(id=snap_id).update(
                            {
                                "enrich_attempts": LicitacionSnapshot.enrich_attempts + 1,
                                "last_enrich_error": "listado_vacio",
                            },
                            synchronize_session=False,
                        )
                    continue
                norm = normalizar_orden_compra(listado[0])

            fp = None
            if norm.get("fecha_publicacion"):
                try:
                    fp = datetime.strptime(norm["fecha_publicacion"], "%Y-%m-%d")
                except Exception:
                    pass

            now_u = datetime.now(timezone.utc).replace(tzinfo=None)
            with get_db() as db:
                db.query(LicitacionSnapshot).filter_by(id=snap_id).update(
                    {
                        "datos": norm,
                        "region": norm.get("region"),
                        "monto_clp": norm.get("monto_clp"),
                        "estado": norm.get("estado"),
                        "fecha_publicacion": fp,
                        "detalle_obtenido_en": now_u,
                        "enrich_attempts": LicitacionSnapshot.enrich_attempts + 1,
                        "last_enrich_error": None,
                    },
                    synchronize_session=False,
                )
            ok += 1

        except (QuotaExhaustedException, RateLimitedException) as e:
            incompleto = True
            motivo_corte = str(e)
            print(
                f"\n  {R}Corte limpio en ítem {i}/{len(codigos)}: {motivo_corte}{NC}"
            )
            print(
                f"  {Y}Sincronización de enriquecimiento marcada INCOMPLETA. "
                f"Reanudar más tarde (queda {len(codigos) - i + 1} pendientes de este lote).{NC}"
            )
            break
        except ApiClientException as e:
            err += 1
            with get_db() as db:
                db.query(LicitacionSnapshot).filter_by(id=snap_id).update(
                    {
                        "enrich_attempts": LicitacionSnapshot.enrich_attempts + 1,
                        "last_enrich_error": redact_secrets(str(e))[:400],
                    },
                    synchronize_session=False,
                )
            if err <= 5:
                print(f"  {R}Error API {codigo}: {redact_secrets(str(e))}{NC}")
        except Exception as e:
            err += 1
            with get_db() as db:
                db.query(LicitacionSnapshot).filter_by(id=snap_id).update(
                    {
                        "enrich_attempts": LicitacionSnapshot.enrich_attempts + 1,
                        "last_enrich_error": redact_secrets(str(e))[:400],
                    },
                    synchronize_session=False,
                )
            if err <= 5:
                print(f"  {R}Error {codigo}: {redact_secrets(str(e))}{NC}")

        if i % lote == 0 or i == len(codigos):
            pct = i / len(codigos) * 100
            bar = "\u2588" * int(pct / 2.5) + "\u2591" * (40 - int(pct / 2.5))
            print(
                f"\r  [{bar}] {i:,}/{len(codigos):,} ({pct:.0f}%) \u2705{ok} \u274c{err} \u23ed{omit}",
                end="",
                flush=True,
            )
            if i < len(codigos) and not incompleto:
                time.sleep(0.5)

    print()
    status_color = Y if incompleto else G
    status_txt = "INCOMPLETO" if incompleto else "COMPLETO"
    print(
        f"\n  {status_color}Estado: {status_txt}{NC}  "
        f"{G}\u2705 Enriquecidos: {ok:,}{NC}  \u274c Errores: {err}  \u23ed Omitidos: {omit}"
    )
    if incompleto and motivo_corte:
        print(f"  Motivo corte: {motivo_corte}")

    with get_db() as db:
        sin_region = (
            db.query(LicitacionSnapshot)
            .filter(LicitacionSnapshot.region.is_(None))
            .count()
        )
    print(f"  Quedan sin región: {sin_region:,}\n")

    finish_sync_run(
        run_id,
        estado="incompleto" if incompleto else "completo",
        motivo=motivo_corte or None,
        items_ok=ok,
        items_fail=err,
    )
    return 2 if incompleto else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Enriquecer snapshots con detalle API")
    p.add_argument("--limite", type=int, default=50, help="Máx a procesar (default 50)")
    p.add_argument("--todos", action="store_true", help="Procesar todos los pendientes")
    p.add_argument("--force", action="store_true", help="Permitir >50 fuera de ventana valle")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--lote", type=int, default=50)
    p.add_argument("--solo-sin-region", action="store_true", default=True)
    p.add_argument("--incluir-con-region", action="store_true")
    args = p.parse_args()
    solo = not args.incluir_con_region
    limite = None if args.todos else args.limite
    code = run(limite, args.dry_run, solo, max(1, args.lote), force=args.force)
    sys.exit(code)
