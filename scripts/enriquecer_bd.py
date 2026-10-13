#!/usr/bin/env python3
"""
scripts/enriquecer_bd.py
Enriquece los snapshots existentes que solo tienen datos del listado
(sin región, monto, organismo) llamando al endpoint de detalle por cada código.

Diseño Fase 1 / Objetivo 1:
  - Ritmo suave (API_ENRICH_RATE_PER_SECOND, default 2 req/s)
  - Lotes de 50 (configurable)
  - Respeta 429 / Retry-After / circuit breaker del cliente
  - Marca corrida como incompleta si se corta por cuota o rate limit
  - Preferir ventana valle 22:00–07:00 America/Santiago

Uso:
  python scripts/enriquecer_bd.py --limite 30
  python scripts/enriquecer_bd.py --limite 500 --lote 50
  python scripts/enriquecer_bd.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
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
VALLE_INICIO = 22  # 22:00
VALLE_FIN = 7      # 07:00


def _en_ventana_valle(now: datetime | None = None) -> bool:
    now = now or datetime.now(TZ_CL)
    h = now.hour
    return h >= VALLE_INICIO or h < VALLE_FIN


def run(limite: int | None, dry_run: bool, solo_sin_region: bool, lote: int) -> int:
    """
    Returns exit code:
      0 = completado (o dry-run)
      2 = incompleto (cortado por cuota / rate limit)
      1 = error inesperado
    """
    init_db()
    client = make_enrich_client()
    rate = getattr(settings, "API_ENRICH_RATE_PER_SECOND", 2.0)

    with get_db() as db:
        q = db.query(LicitacionSnapshot)
        if solo_sin_region:
            q = q.filter(LicitacionSnapshot.region.is_(None))
        total_pendiente = q.count()
        pendientes = q.limit(limite).all() if limite else q.all()
        codigos = [(s.id, s.codigo, s.tipo) for s in pendientes]

    print(f"\n{B}Enriquecer BD — fetch detalle por código{NC}")
    print(f"  Pendientes : {total_pendiente:,} snapshots sin región/monto")
    print(f"  A procesar : {len(codigos):,}")
    print(f"  Lote       : {lote}")
    print(f"  Ritmo      : {rate} req/s (techo diario {settings.API_RATE_PER_DAY:,})")
    print(f"  Modo       : {'DRY RUN' if dry_run else 'ESCRITURA'}")

    now_cl = datetime.now(TZ_CL)
    if not _en_ventana_valle(now_cl):
        print(
            f"  {Y}Aviso: fuera de ventana valle (22:00–07:00 CL). "
            f"Ahora {now_cl.strftime('%H:%M %Z')}. Preferir horario bajo para no competir con sync.{NC}"
        )
    else:
        print(f"  {G}Ventana valle OK ({now_cl.strftime('%H:%M %Z')}){NC}")
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

    for i, (snap_id, codigo, tipo) in enumerate(codigos, 1):
        try:
            if tipo == "licitacion":
                detalle = client.get_licitacion_detalle(codigo)
                if not detalle:
                    omit += 1
                    continue
                norm = normalizar_licitacion(detalle)
            else:
                data = client._get("publico/ordenesdecompra.json", {"codigo": codigo})
                listado = data.get("Listado") or []
                if not listado:
                    omit += 1
                    continue
                norm = normalizar_orden_compra(listado[0])

            fp = None
            if norm.get("fecha_publicacion"):
                try:
                    fp = datetime.strptime(norm["fecha_publicacion"], "%Y-%m-%d")
                except Exception:
                    pass

            with get_db() as db:
                db.query(LicitacionSnapshot).filter_by(id=snap_id).update(
                    {
                        "datos": norm,
                        "region": norm.get("region"),
                        "monto_clp": norm.get("monto_clp"),
                        "estado": norm.get("estado"),
                        "fecha_publicacion": fp,
                    }
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
            if err <= 5:
                print(f"  {R}Error API {codigo}: {redact_secrets(str(e))}{NC}")
        except Exception as e:
            err += 1
            if err <= 5:
                print(f"  {R}Error {codigo}: {redact_secrets(str(e))}{NC}")

        # Progreso cada lote o al final
        if i % lote == 0 or i == len(codigos):
            pct = i / len(codigos) * 100
            bar = "█" * int(pct / 2.5) + "░" * (40 - int(pct / 2.5))
            print(
                f"\r  [{bar}] {i:,}/{len(codigos):,} ({pct:.0f}%) ✅{ok} ❌{err} ⏭{omit}",
                end="",
                flush=True,
            )
            # Pausa breve entre lotes para suavizar aún más
            if i < len(codigos) and not incompleto:
                time.sleep(0.5)

    print()
    status_color = Y if incompleto else G
    status_txt = "INCOMPLETO" if incompleto else "COMPLETO"
    print(
        f"\n  {status_color}Estado: {status_txt}{NC}  "
        f"{G}✅ Enriquecidos: {ok:,}{NC}  ❌ Errores: {err}  ⏭ Omitidos: {omit}"
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

    return 2 if incompleto else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Enriquecer snapshots con detalle API")
    p.add_argument(
        "--limite",
        type=int,
        default=0,
        help="Máx a procesar (0=todos)",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--lote",
        type=int,
        default=50,
        help="Tamaño de lote para progreso y pausa suave (default 50)",
    )
    p.add_argument(
        "--solo-sin-region",
        action="store_true",
        default=True,
        help="Solo procesar snapshots sin región (default: True)",
    )
    p.add_argument(
        "--incluir-con-region",
        action="store_true",
        help="Procesar también los que ya tienen región",
    )
    args = p.parse_args()
    solo = not args.incluir_con_region
    code = run(args.limite or None, args.dry_run, solo, max(1, args.lote))
    sys.exit(code)
