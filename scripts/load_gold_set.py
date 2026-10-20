#!/usr/bin/env python3
"""Carga fichas gold set (JSON) a tabla gold_bases. No inventa datos."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal, init_db
from app.models import GoldBase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gold")

VALID_VERTICAL = {"TI", "Construccion"}


def load_file(path: Path, dry_run: bool) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    codigo = (data.get("codigo") or "").strip()
    vertical = (data.get("vertical") or "").strip()
    if not codigo or vertical not in VALID_VERTICAL:
        return "skip"
    if dry_run:
        return "ok"
    with SessionLocal() as db:
        row = (
            db.query(GoldBase)
            .filter_by(codigo=codigo, vertical=vertical)
            .one_or_none()
        )
        if row is None:
            row = GoldBase(codigo=codigo, vertical=vertical)
            db.add(row)
        row.titulo = data.get("titulo")
        row.pdf_path = data.get("pdf_path")
        row.anotacion = data.get("anotacion") or {}
        row.notas = data.get("notas")
        db.commit()
    return "upsert"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/gold_set")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    init_db()
    d = Path(args.dir)
    files = sorted(d.glob("*.json"))
    files = [f for f in files if "template" not in f.name.lower()]
    stats = {"upsert": 0, "ok": 0, "skip": 0}
    for f in files:
        st = load_file(f, args.dry_run)
        stats[st] = stats.get(st, 0) + 1
        log.info("%s → %s", f.name, st)
    log.info("FIN %s (%d archivos)", stats, len(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
