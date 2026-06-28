"""app/filter_engine.py — Motor de evaluación de filtros multi-operador."""
from __future__ import annotations
import logging
from datetime import date
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class FiltroInvalidoError(Exception): pass

def _str_ci(v): return str(v).lower().strip() if v is not None else ""
def _to_date(v):
    if not v: return None
    try: return date.fromisoformat(str(v)[:10])
    except: return None
def _norm_codigos(raw):
    if raw is None: return []
    if isinstance(raw, list): return [str(c).strip() for c in raw if c]
    return [str(raw).strip()]

_OPERADORES = {
    "region":                  lambda val, e: int(e.get("region") or -1) == int(val),
    "region_in":               lambda val, e: int(e.get("region") or -1) in [int(r) for r in val],
    "monto_min":               lambda val, e: (e.get("monto_clp") or 0) >= int(val),
    "monto_max":               lambda val, e: (e.get("monto_clp") or 0) <= int(val),
    "titulo_contains":         lambda val, e: _str_ci(val) in _str_ci(e.get("titulo")),
    "titulo_not_contains":     lambda val, e: _str_ci(val) not in _str_ci(e.get("titulo")),
    "descripcion_contains":    lambda val, e: _str_ci(val) in _str_ci(e.get("descripcion")),
    "organismo_contains":      lambda val, e: _str_ci(val) in _str_ci(e.get("organismo")),
    "codigo_producto":         lambda val, e: str(val).strip() in _norm_codigos(e.get("codigo_producto")),
    "codigo_producto_in":      lambda val, e: bool(set(_norm_codigos(e.get("codigo_producto"))) & set(str(v).strip() for v in val)),
    "estado":                  lambda val, e: _str_ci(e.get("estado")) == _str_ci(val),
    "estado_in":               lambda val, e: _str_ci(e.get("estado")) in [_str_ci(v) for v in val],
}
FILTROS_VALIDOS = set(_OPERADORES.keys())
OPERADORES_VALIDOS = FILTROS_VALIDOS  # alias

def evaluar_regla(regla, entidad: Dict) -> bool:
    filtros = getattr(regla, "filtros", None) or {}
    if not filtros: return True
    for clave, valor in filtros.items():
        if valor is None or valor == "" or valor == [] or valor == {}: continue
        evaluador = _OPERADORES.get(clave)
        if evaluador is None:
            logger.warning("Operador desconocido '%s' — ignorando", clave); continue
        try:
            if not evaluador(valor, entidad): return False
        except Exception as e:
            logger.warning("Error evaluando '%s'=%r: %s", clave, valor, e); return False
    return True

def validar_filtros(filtros: Dict) -> List[str]:
    errores = []
    for clave, valor in filtros.items():
        if clave not in FILTROS_VALIDOS:
            errores.append(f"Operador desconocido: '{clave}'"); continue
        if clave in ("region","monto_min","monto_max"):
            try: int(valor)
            except: errores.append(f"'{clave}' debe ser número entero, recibido: {valor!r}")
        if clave in ("region_in","estado_in","codigo_producto_in"):
            if not isinstance(valor, list):
                errores.append(f"'{clave}' debe ser una lista, recibido: {type(valor).__name__}")
    return errores

def describe_filtros(filtros: Dict) -> str:
    """Descripción legible de los filtros para el dashboard."""
    if not filtros: return "Sin filtros"
    partes = []
    nombres = {
        "region": "Región", "region_in": "Regiones", "monto_min": "Monto mín",
        "monto_max": "Monto máx", "titulo_contains": "Título contiene",
        "titulo_not_contains": "Título NO contiene", "descripcion_contains": "Descripción contiene",
        "organismo_contains": "Organismo contiene", "codigo_producto": "Categoría",
        "codigo_producto_in": "Categorías", "estado": "Estado", "estado_in": "Estados",
    }
    for k, v in filtros.items():
        if v is None or v == "" or v == []: continue
        nombre = nombres.get(k, k)
        if isinstance(v, list): partes.append(f"{nombre}: {', '.join(str(x) for x in v)}")
        else: partes.append(f"{nombre}: {v}")
    return " · ".join(partes) if partes else "Sin filtros"
