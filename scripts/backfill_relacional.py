#!/usr/bin/env python3
"""Backfill Obj5: snapshot → tablas relacionales SIN llamar a la API.

Uso:
  python scripts/backfill_relacional.py --limite 500
  python scripts/backfill_relacional.py --todos --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal, init_db
from app.models import LicitacionSnapshot
from app.relacional import upsert_snapshot_relacional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill")


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill relacional desde snapshots (sin API)")
    ap.add_argument("--limite", type=int, default=500, help="Máx snapshots (0=todos)")
    ap.add_argument("--todos", action="store_true", help="Equivale a --limite 0")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--offset", type=int, default=0)
    args = ap.parse_args()

    init_db()
    limite = 0 if args.todos else args.limite

    with SessionLocal() as db:
        q = db.query(LicitacionSnapshot.id).order_by(LicitacionSnapshot.id)
        if args.offset:
            q = q.offset(args.offset)
        if limite and limite > 0:
            q = q.limit(limite)
        ids = [r[0] for r in q.all()]

    stats = {"new": 0, "updated": 0, "unchanged": 0, "skip": 0}
    log.info("Backfill %d snapshots (dry_run=%s)", len(ids), args.dry_run)

    with SessionLocal() as db:
        for i, sid in enumerate(ids, 1):
            snap = db.query(LicitacionSnapshot).filter_by(id=sid).one()
            st = upsert_snapshot_relacional(db, snap, dry_run=args.dry_run)
            stats[st] = stats.get(st, 0) + 1
            if i % 100 == 0:
                if not args.dry_run:
                    db.commit()
                log.info("… %d/%d %s", i, len(ids), stats)
        if not args.dry_run:
            db.commit()

    log.info("FIN %s", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
