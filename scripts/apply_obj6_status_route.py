#!/usr/bin/env python3
"""Parchea app/dashboard/routes.py para usar status_api.build_status_response (Obj6)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "app" / "dashboard" / "routes.py"

OLD = re.compile(
    r'@bp\.route\("/api/status"\)\s*\n@login_required\s*\ndef api_status\(\):.*?\n(?=@bp\.route\("/api/quota"\))',
    re.S,
)

NEW = '''@bp.route("/api/status")
@login_required
def api_status():
    """Obj6: estado real BD, outbox, sync, cuota global, scheduler."""
    from app.dashboard.status_api import build_status_response
    return build_status_response()


'''


def main() -> int:
    text = ROUTES.read_text(encoding="utf-8")
    if "build_status_response" in text:
        print("routes.py ya usa status_api — OK")
        return 0
    new_text, n = OLD.subn(NEW, text, count=1)
    if n != 1:
        print("ERROR: no se encontro el bloque api_status esperado")
        return 1
    ROUTES.write_text(new_text, encoding="utf-8")
    print("OK: routes.py parcheado → status_api.build_status_response")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
