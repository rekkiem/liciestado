"""Normalización de RUT chileno (Obj5)."""
from __future__ import annotations

import re
from typing import Optional


def normalizar_rut(value: Optional[str]) -> Optional[str]:
    """Devuelve RUT canónico: solo dígitos + DV (K mayúscula), sin puntos ni guión.

    Ejemplos:
      "12.345.678-9" -> "123456789"
      "12345678-k"   -> "12345678K"
      "" / None      -> None
    """
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    s = s.replace(".", "").replace(" ", "").replace("-", "")
    # Solo dígitos + K final opcional
    if not re.fullmatch(r"\d{7,8}[0-9K]", s):
        # intentar limpiar basura residual
        s2 = re.sub(r"[^0-9K]", "", s)
        if re.fullmatch(r"\d{7,8}[0-9K]", s2):
            return s2
        return None
    return s


def rut_display(normalized: Optional[str]) -> Optional[str]:
    """Formato con guión: 12345678-9."""
    n = normalizar_rut(normalized) if normalized else None
    if not n or len(n) < 2:
        return None
    return f"{n[:-1]}-{n[-1]}"
