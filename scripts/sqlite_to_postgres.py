#!/usr/bin/env python3
"""
scripts/sqlite_to_postgres.py
Migra datos de SQLite → PostgreSQL (Fase 1 / Objetivo 2).

Características (Architect):
  - Orden FK seguro (padres → hijos)
  - Reset de secuencias (setval) tras COPY
  - Conteos por tabla + verificación
  - --dry-run (solo reporta, no escribe)
  - Coerción de tipos (bool, datetime, JSON)
  - Errores de copia → exit code != 0
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("sqlite_to_postgres")

TABLE_ORDER = [
    "users",
    "user_tickets",
    "user_configs",
    "reglas_usuario",
    "licitaciones_snapshot",
    "alertas_generadas",
    "webhook_logs",
    "api_quota_logs",
]

JSON_COLUMNS = {
    "reglas_usuario": {"filtros"},
    "alertas_generadas": {"datos_resumen"},
    "licitaciones_snapshot": {"datos"},
    "webhook_logs": {"payload_json"},
}


def _engine(url: str) -> Engine:
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


def _table_exists(eng: Engine, name: str) -> bool:
    return name in inspect(eng).get_table_names()


def _columns(eng: Engine, table: str) -> list[str]:
    return [c["name"] for c in inspect(eng).get_columns(table)]


def _count(eng: Engine, table: str) -> int:
    with eng.connect() as conn:
        return int(conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0)


def _fetch_rows(eng: Engine, table: str, cols: list[str], batch: int):
    col_list = ", ".join(f'"{c}"' for c in cols)
    sql = text(f'SELECT {col_list} FROM "{table}"')
    with eng.connect() as conn:
        result = conn.execute(sql)
        while True:
            rows = result.fetchmany(batch)
            if not rows:
                break
            yield [dict(zip(cols, row)) for row in rows]


def _col_types(eng: Engine, table: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in inspect(eng).get_columns(table):
        typ = c.get("type")
        out[c["name"]] = type(typ).__name__.lower() if typ is not None else ""
    return out


def _prepare_value(table: str, col: str, val: Any, col_type: str = "") -> Any:
    if val is None:
        return None
    json_cols = JSON_COLUMNS.get(table, set())
    if col in json_cols or "json" in col_type:
        if isinstance(val, (dict, list)):
            return val
        if isinstance(val, (bytes, bytearray)):
            val = val.decode("utf-8", errors="replace")
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return val
        return val
    if "bool" in col_type:
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str):
            return val.strip().lower() in ("1", "true", "t", "yes", "y")
        return bool(val)
    if "date" in col_type or "time" in col_type:
        if hasattr(val, "isoformat"):
            return val
        if isinstance(val, str):
            from datetime import datetime

            s = val.strip()
            for fmt in (
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d",
            ):
                try:
                    return datetime.strptime(s[:26], fmt)
                except ValueError:
                    continue
            return val
    return val


def _reset_sequences(pg: Engine, tables: list[str]) -> None:
    with pg.begin() as conn:
        for table in tables:
            if not _table_exists(pg, table):
                continue
            cols = _columns(pg, table)
            if "id" not in cols:
                continue
            seq = f"{table}_id_seq"
            exists = conn.execute(
                text("SELECT 1 FROM pg_class WHERE relname = :s AND relkind = 'S'"),
                {"s": seq},
            ).scalar()
            if not exists:
                seq_name = conn.execute(
                    text("SELECT pg_get_serial_sequence(:t, 'id')"),
                    {"t": table},
                ).scalar()
                if not seq_name:
                    continue
                seq = seq_name
            max_id = conn.execute(
                text(f'SELECT COALESCE(MAX(id), 0) FROM "{table}"')
            ).scalar()
            conn.execute(
                text("SELECT setval(CAST(:seq AS regclass), :m, true)"),
                {"seq": seq, "m": int(max_id)},
            )
            logger.info("  setval %s → %s", seq, max_id)


def migrate(
    sqlite_url: str,
    postgres_url: str,
    *,
    dry_run: bool,
    batch_size: int,
    skip_existing: bool,
    tables: list[str] | None,
) -> int:
    src = _engine(sqlite_url)
    dst = _engine(postgres_url)

    selected = tables or [t for t in TABLE_ORDER if _table_exists(src, t)]
    missing_src = [t for t in selected if not _table_exists(src, t)]
    missing_dst = [t for t in selected if not _table_exists(dst, t)]
    if missing_dst:
        logger.error(
            "Tablas ausentes en Postgres (¿corriste alembic upgrade head?): %s",
            missing_dst,
        )
        return 1
    if missing_src:
        logger.warning("Tablas ausentes en SQLite (se omiten): %s", missing_src)
        selected = [t for t in selected if t not in missing_src]

    print("\n=== sqlite → postgres ===")
    print(f"  source : {sqlite_url}")
    print(f"  dest   : {postgres_url}")
    print(f"  mode   : {'DRY-RUN' if dry_run else 'WRITE'}")
    print(f"  tables : {', '.join(selected)}\n")

    report: list[tuple[str, int, int, int]] = []

    for table in selected:
        src_cols = _columns(src, table)
        dst_cols = set(_columns(dst, table))
        cols = [c for c in src_cols if c in dst_cols]
        if not cols:
            logger.warning("Sin columnas en común en %s — skip", table)
            continue

        n_src = _count(src, table)
        n_dst_before = _count(dst, table)
        print(f"  {table}: sqlite={n_src:,}  postgres_antes={n_dst_before:,}")

        if dry_run:
            report.append((table, n_src, n_dst_before, 0))
            continue

        copied = 0
        col_list = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join(f":{c}" for c in cols)
        dst_types = _col_types(dst, table)
        if skip_existing and "id" in cols:
            insert_sql = text(
                f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) '
                f"ON CONFLICT (id) DO NOTHING"
            )
        else:
            insert_sql = text(
                f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})'
            )

        try:
            with dst.begin() as conn:
                for batch in _fetch_rows(src, table, cols, batch_size):
                    payload = [
                        {
                            c: _prepare_value(
                                table, c, row[c], dst_types.get(c, "")
                            )
                            for c in cols
                        }
                        for row in batch
                    ]
                    if not payload:
                        continue
                    conn.execute(insert_sql, payload)
                    copied += len(payload)
        except Exception as e:
            logger.exception("Error copiando tabla %s: %s", table, e)
            print(f"    ERROR en {table}: {e}")
            return 1

        n_dst_after = _count(dst, table)
        print(f"    → copiados={copied:,}  postgres_despues={n_dst_after:,}")
        report.append((table, n_src, n_dst_before, copied))

    if not dry_run:
        print("\n  Reseteando secuencias…")
        try:
            _reset_sequences(dst, selected)
        except Exception as e:
            logger.warning("setval falló (revisar manualmente): %s", e)

    print("\n=== Resumen ===")
    ok = True
    for table, n_src, n_before, copied in report:
        n_after = _count(dst, table) if not dry_run else n_before
        status = "OK"
        if not dry_run:
            if n_after < n_src and not skip_existing:
                status = "WARN conteo destino < origen"
                ok = False
            elif skip_existing and n_after < n_src:
                status = "OK (skip-existing)"
        print(f"  {table:24} src={n_src:8,}  dst={n_after:8,}  +{copied:8,}  {status}")

    print()
    return 0 if ok else 2


def main() -> None:
    p = argparse.ArgumentParser(description="Migrar SQLite → PostgreSQL")
    p.add_argument("--sqlite", required=True, help="URL SQLAlchemy SQLite origen")
    p.add_argument("--postgres", required=True, help="URL SQLAlchemy PostgreSQL destino")
    p.add_argument("--dry-run", action="store_true", help="Solo reportar conteos")
    p.add_argument("--batch-size", type=int, default=500)
    p.add_argument("--skip-existing", action="store_true", help="ON CONFLICT (id) DO NOTHING")
    p.add_argument("--tables", nargs="*", default=None)
    args = p.parse_args()
    code = migrate(
        args.sqlite,
        args.postgres,
        dry_run=args.dry_run,
        batch_size=max(1, args.batch_size),
        skip_existing=args.skip_existing,
        tables=args.tables,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
