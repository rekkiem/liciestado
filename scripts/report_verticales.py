#!/usr/bin/env python3
"""Obj6: reporta codigos/rubros observados que delimitan TI vs Construccion.

Solo lee datos locales (snapshot). No llama API.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal, init_db
from app.models import LicitacionSnapshot

TI_KW = re.compile(
    r"\\b(software|inform[aá]tica|tecnolog[ií]a|sistemas?|datos|cloud|"
    r"desarrollo|aplicaci[oó]n|ti\\b|tic|ciber|servidor|redes?|"
    r"hardware|licencia|erp|crm|saas)\\b",
    re.I,
)
CONS_KW = re.compile(
    r"\\b(obra|construcci[oó]n|edificaci[oó]n|paviment|hormig[oó]n|"
    r"arquitectura|remodelaci[oó]n|infraestructura vial|excavaci[oó]n|"
    r"alba[nñ]iler[ií]a|estructura met[aá]lica)\\b",
    re.I,
)


def main() -> int:
    init_db()
    ti = Counter()
    cons = Counter()
    mixed = 0
    neither = 0
    sample_ti, sample_cons = [], []

    with SessionLocal() as db:
        q = db.query(LicitacionSnapshot).limit(5000)
        for s in q:
            d = s.datos or {}
            text = " ".join(
                str(x or "")
                for x in (
                    d.get("titulo"),
                    d.get("descripcion"),
                    d.get("codigo_producto"),
                    s.tipo,
                )
            )
            is_ti = bool(TI_KW.search(text))
            is_c = bool(CONS_KW.search(text))
            if is_ti and not is_c:
                ti[s.tipo or "?"] += 1
                if len(sample_ti) < 5:
                    sample_ti.append({"codigo": s.codigo, "titulo": (d.get("titulo") or "")[:80]})
            elif is_c and not is_ti:
                cons[s.tipo or "?"] += 1
                if len(sample_cons) < 5:
                    sample_cons.append({"codigo": s.codigo, "titulo": (d.get("titulo") or "")[:80]})
            elif is_ti and is_c:
                mixed += 1
            else:
                neither += 1

    report = {
        "nota": "Clasificacion heuristica por keywords en titulo/descripcion de snapshots locales.",
        "ti": {"por_tipo": dict(ti), "ejemplos": sample_ti},
        "construccion": {"por_tipo": dict(cons), "ejemplos": sample_cons},
        "mixtos": mixed,
        "sin_match": neither,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
