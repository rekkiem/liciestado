"""app/normalizer.py — Normalización de entidades de la API de Mercado Público."""
from __future__ import annotations
import logging, re
from datetime import datetime
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

_LIC_DETAIL_URL = "https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?qs={codigo}"
_OC_DETAIL_URL  = "https://www.mercadopublico.cl/Procurement/Modules/PO/DetailsPurchaseOrder.aspx?codigoOC={codigo}"
_FX_RATES: Dict[str, float] = {"CLP":1.0,"USD":900.0,"EUR":980.0,"UF":37_500.0,"UTM":65_000.0}

_ESTADO_LIC_MAP = {"1":"Borrador","2":"Publicada","3":"Cerrada","4":"Desierta","5":"Adjudicada","6":"Revocada","7":"Suspendida","8":"Publicada","9":"Publicada","16":"Desierta (Admin)","17":"Revocada (Admin)"}
_ESTADO_OC_MAP  = {"1":"Enviada","2":"Aceptada","3":"Rechazada","4":"Cancelada","5":"Enviada","6":"Aceptada","7":"Parcialmente Recibida","8":"Recibida","9":"Cerrada","10":"Cancelada","11":"Pendiente","12":"Procesando","13":"Enviada al Proveedor","14":"Entregada","15":"Pagada"}
_ESTADO_MAP = {**_ESTADO_LIC_MAP}

def _resolve_estado(raw: Dict, es_oc: bool = False) -> str:
    estado = raw.get("Estado") or ""
    if estado: return estado
    codigo = str(raw.get("CodigoEstado") or "").strip()
    if not codigo: return ""
    mapa = _ESTADO_OC_MAP if es_oc else _ESTADO_LIC_MAP
    return mapa.get(codigo, _ESTADO_MAP.get(codigo, f"Estado {codigo}"))

def _to_clp(amount, currency):
    if amount is None: return None
    return int(float(amount) * _FX_RATES.get(str(currency).upper(), 1.0))

def _parse_date(raw):
    if not raw: return None
    ms_match = re.match(r"/Date\((-?\d+)\)/", str(raw))
    if ms_match:
        try: return datetime.utcfromtimestamp(int(ms_match.group(1))/1000).strftime("%Y-%m-%d")
        except: return None
    clean = str(raw).strip().rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S","%Y-%m-%dT%H:%M","%Y-%m-%d","%d-%m-%Y","%d/%m/%Y"):
        for frag in (clean[:19],clean[:16],clean[:10]):
            try: return datetime.strptime(frag, fmt).strftime("%Y-%m-%d")
            except: continue
    return None

def _extract_region(comprador):
    codigo = comprador.get("CodigoRegion") or comprador.get("Region")
    nombre = comprador.get("NombreRegion")
    try: codigo = int(codigo) if codigo is not None else None
    except: codigo = None
    return codigo, nombre

def _extract_productos(items_raw):
    if not items_raw: return []
    listado = items_raw.get("Listado",[]) if isinstance(items_raw,dict) else (items_raw if isinstance(items_raw,list) else [])
    return [str(item.get("CodigoProducto") or item.get("CodigoCategoria","")) for item in listado if isinstance(item,dict) and (item.get("CodigoProducto") or item.get("CodigoCategoria"))]

def normalizar_licitacion(raw: Dict) -> Dict:
    comprador = raw.get("Comprador") or {}
    region, nombre_region = _extract_region(comprador)
    monto_raw = raw.get("MontoEstimado")
    moneda_raw = raw.get("Moneda") or "CLP"
    try: monto_raw = float(monto_raw) if monto_raw is not None else None
    except: monto_raw = None
    monto_clp = _to_clp(monto_raw, moneda_raw)
    codigo = raw.get("CodigoExterno") or raw.get("Codigo") or ""
    fecha_pub = _parse_date(raw.get("FechaPublicacion") or raw.get("FechaCreacion"))
    return {
        "tipo": "licitacion", "codigo": codigo,
        "titulo": raw.get("Nombre") or "", "descripcion": raw.get("Descripcion") or "",
        "estado": _resolve_estado(raw), "region": region, "nombre_region": nombre_region,
        "organismo": comprador.get("NombreOrganismo"), "codigo_organismo": comprador.get("CodigoOrganismo"),
        "fecha_publicacion": fecha_pub, "fecha_cierre": _parse_date(raw.get("FechaCierre")),
        "monto_clp": monto_clp, "moneda": "CLP",
        "codigo_producto": _extract_productos(raw.get("Items")),
        "link_detalle": _LIC_DETAIL_URL.format(codigo=codigo),
        "_enriquecido": bool(comprador or monto_clp or fecha_pub), "_raw": raw,
    }

def normalizar_orden_compra(raw: Dict) -> Dict:
    comprador = raw.get("Comprador") or {}
    region, nombre_region = _extract_region(comprador)
    monto_raw = raw.get("MontoTotal") or raw.get("Monto")
    moneda_raw = raw.get("Moneda") or "CLP"
    try: monto_raw = float(monto_raw) if monto_raw is not None else None
    except: monto_raw = None
    codigo = raw.get("Numero") or raw.get("CodigoExterno") or raw.get("Codigo") or ""
    return {
        "tipo": "orden_compra", "codigo": codigo,
        "titulo": raw.get("Nombre") or raw.get("Descripcion") or "",
        "descripcion": raw.get("Descripcion") or "",
        "estado": _resolve_estado(raw, es_oc=True), "region": region, "nombre_region": nombre_region,
        "organismo": comprador.get("NombreOrganismo"), "codigo_organismo": comprador.get("CodigoOrganismo"),
        "fecha_publicacion": _parse_date(raw.get("FechaEnvio") or raw.get("FechaCreacion")),
        "fecha_cierre": None, "monto_clp": _to_clp(monto_raw, moneda_raw), "moneda": "CLP",
        "codigo_producto": _extract_productos(raw.get("Items")),
        "link_detalle": _OC_DETAIL_URL.format(codigo=codigo),
        "_enriquecido": bool(comprador or monto_raw), "_raw": raw,
    }

def normalizar_entidad(raw: Dict, tipo: str) -> Optional[Dict]:
    if not raw: return None
    tipo_real = raw.get("_api_tipo") or tipo
    try:
        if tipo_real in ("licitacion","L1","LE","LP","LQ","LR","LS"): return normalizar_licitacion(raw)
        elif tipo_real == "orden_compra": return normalizar_orden_compra(raw)
        elif tipo_real in ("compra_agil","CO"): n = normalizar_licitacion(raw); n["tipo"]="compra_agil"; return n
        else: return normalizar_licitacion(raw)
    except Exception as e:
        logger.exception("Error normalizando (tipo=%s): %s", tipo, e); return None

def datos_resumen(entidad: Dict) -> Dict:
    return {k: entidad.get(k) for k in ["tipo","codigo","titulo","organismo","monto_clp","moneda","estado","region","nombre_region","fecha_publicacion","fecha_cierre","link_detalle","codigo_producto"]}
