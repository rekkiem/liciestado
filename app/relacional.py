"""Helpers Obj5: hash de contenido + extraccion desde snapshot.datos."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.rut import normalizar_rut


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def content_hash(payload: Dict[str, Any]) -> str:
    """SHA-256 del detalle canonico (sin timestamps de sync)."""
    raw = payload.get("_raw") if isinstance(payload.get("_raw"), dict) else payload
    subset = {
        "codigo": payload.get("codigo") or (raw or {}).get("CodigoExterno") or (raw or {}).get("Codigo"),
        "titulo": payload.get("titulo") or (raw or {}).get("Nombre"),
        "estado": payload.get("estado") or (raw or {}).get("CodigoEstado"),
        "monto": payload.get("monto_clp"),
        "organismo": payload.get("codigo_organismo") or payload.get("organismo"),
        "items": (raw or {}).get("Items") if isinstance(raw, dict) else None,
        "adjudicacion": (raw or {}).get("Adjudicacion") if isinstance(raw, dict) else None,
    }
    return hashlib.sha256(_canon(subset).encode("utf-8")).hexdigest()


def _parse_dt(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None) if v.tzinfo else v
    s = str(v).strip()
    if not s:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(s[:26].replace("Z", ""), fmt)
        except ValueError:
            continue
    return None


def extract_from_datos(datos: Dict[str, Any], tipo: str = "licitacion") -> Dict[str, Any]:
    """Extrae filas relacionales desde snapshot.datos (normalizado o raw)."""
    d = datos or {}
    raw = d.get("_raw") if isinstance(d.get("_raw"), dict) else {}
    codigo = (d.get("codigo") or raw.get("CodigoExterno") or raw.get("Codigo") or "").strip()
    org_codigo = d.get("codigo_organismo") or (raw.get("Comprador") or {}).get("CodigoOrganismo") or None
    org_nombre = d.get("organismo") or (raw.get("Comprador") or {}).get("NombreOrganismo") or None
    region = d.get("region")
    if region is None:
        try:
            region = int((raw.get("Comprador") or {}).get("CodigoRegion") or 0) or None
        except (TypeError, ValueError):
            region = None

    lic = {
        "codigo": codigo,
        "tipo": d.get("tipo") or tipo or "licitacion",
        "titulo": d.get("titulo") or raw.get("Nombre") or "",
        "estado": d.get("estado") or raw.get("CodigoEstado") or None,
        "fecha_publicacion": _parse_dt(d.get("fecha_publicacion") or raw.get("FechaPublicacion")),
        "fecha_cierre": _parse_dt(d.get("fecha_cierre") or raw.get("FechaCierre")),
        "monto_clp": d.get("monto_clp"),
        "organismo_codigo": str(org_codigo).strip() if org_codigo else None,
        "organismo_nombre": org_nombre,
        "region": region,
        "link_detalle": d.get("link_detalle"),
    }

    items: List[Dict[str, Any]] = []
    raw_items = raw.get("Items")
    if isinstance(raw_items, dict):
        lista = raw_items.get("Listado") or raw_items.get("Item") or []
        if isinstance(lista, dict):
            lista = [lista]
        for it in lista or []:
            if not isinstance(it, dict):
                continue
            items.append({
                "codigo_item": str(it.get("CodigoProducto") or it.get("Codigo") or "")[:80] or None,
                "descripcion": (it.get("Descripcion") or it.get("NombreProducto") or "")[:2000] or None,
                "cantidad": it.get("Cantidad"),
                "unidad": it.get("UnidadMedida") or it.get("Unidad"),
                "monto_unitario": it.get("MontoUnitario") or it.get("PrecioNeto"),
            })

    adjudicaciones: List[Dict[str, Any]] = []
    adj_block = raw.get("Adjudicacion") or raw.get("Adjudicaciones")
    if not adj_block and isinstance(raw_items, dict):
        for it in (raw_items.get("Listado") or []):
            if not isinstance(it, dict):
                continue
            a = it.get("Adjudicacion")
            if isinstance(a, dict):
                adjudicaciones.append({
                    "rut": normalizar_rut(a.get("RutProveedor") or a.get("Rut")),
                    "nombre": a.get("NombreProveedor") or a.get("Nombre"),
                    "monto": a.get("MontoUnitario") or a.get("MontoLinea") or a.get("Monto"),
                    "fecha": _parse_dt(a.get("Fecha") or a.get("FechaAdjudicacion")),
                })
    elif isinstance(adj_block, dict):
        lista = adj_block.get("Listado") or [adj_block]
        if isinstance(lista, dict):
            lista = [lista]
        for a in lista:
            if not isinstance(a, dict):
                continue
            adjudicaciones.append({
                "rut": normalizar_rut(a.get("RutProveedor") or a.get("Rut")),
                "nombre": a.get("NombreProveedor") or a.get("Nombre"),
                "monto": a.get("MontoUnitario") or a.get("Monto"),
                "fecha": _parse_dt(a.get("Fecha") or a.get("FechaAdjudicacion")),
            })

    return {
        "licitacion": lic,
        "items": items,
        "adjudicaciones": [a for a in adjudicaciones if a.get("rut") or a.get("nombre")],
        "content_hash": content_hash(d),
        "payload": d,
    }


def upsert_snapshot_relacional(db, snap, dry_run: bool = False) -> str:
    """Persiste filas relacionales desde un LicitacionSnapshot. Returns skip|new|updated|unchanged."""
    from app.models import (
        Adjudicacion,
        Item,
        Licitacion,
        LicitacionVersion,
        Organismo,
        Proveedor,
    )

    datos = snap.datos or {}
    extracted = extract_from_datos(datos, tipo=getattr(snap, "tipo", None) or "licitacion")
    lic_data = extracted["licitacion"]
    codigo = (lic_data.get("codigo") or getattr(snap, "codigo", None) or "").strip()
    if not codigo:
        return "skip"

    ch = extracted["content_hash"]
    existing = db.query(Licitacion).filter_by(codigo=codigo).one_or_none()
    if existing and existing.content_hash == ch:
        return "unchanged"
    if dry_run:
        return "new" if existing is None else "updated"

    org_codigo = lic_data.get("organismo_codigo")
    org = None
    if org_codigo:
        org_codigo = str(org_codigo).strip()
        org = db.query(Organismo).filter_by(codigo=org_codigo).one_or_none()
        if org is None:
            org = Organismo(
                codigo=org_codigo,
                nombre=lic_data.get("organismo_nombre"),
                region=lic_data.get("region") if lic_data.get("region") is not None else getattr(snap, "region", None),
            )
            db.add(org)
            db.flush()
        else:
            if lic_data.get("organismo_nombre") and not org.nombre:
                org.nombre = lic_data.get("organismo_nombre")

    if existing is None:
        existing = Licitacion(codigo=codigo)
        db.add(existing)
        status = "new"
    else:
        status = "updated"

    existing.tipo = lic_data.get("tipo") or getattr(snap, "tipo", None) or "licitacion"
    existing.titulo = (lic_data.get("titulo") or "")[:500] or None
    existing.estado = lic_data.get("estado") or getattr(snap, "estado", None)
    existing.fecha_publicacion = lic_data.get("fecha_publicacion") or getattr(snap, "fecha_publicacion", None)
    existing.fecha_cierre = lic_data.get("fecha_cierre")
    monto = lic_data.get("monto_clp")
    if monto is None:
        monto = getattr(snap, "monto_clp", None)
    existing.monto_clp = monto
    if org is not None:
        existing.organismo_id = org.id
    existing.content_hash = ch
    existing.link_detalle = lic_data.get("link_detalle")
    db.flush()

    ver = (
        db.query(LicitacionVersion)
        .filter_by(licitacion_id=existing.id, content_hash=ch)
        .one_or_none()
    )
    if ver is None:
        db.add(
            LicitacionVersion(
                licitacion_id=existing.id,
                content_hash=ch,
                payload=extracted["payload"],
            )
        )
        db.flush()

    db.query(Item).filter_by(licitacion_id=existing.id).delete()
    for it in extracted["items"]:
        unidad = it.get("unidad")
        db.add(
            Item(
                licitacion_id=existing.id,
                codigo_item=it.get("codigo_item"),
                descripcion=it.get("descripcion"),
                cantidad=it.get("cantidad"),
                unidad=(str(unidad)[:40] if unidad else None),
                monto_unitario=it.get("monto_unitario"),
            )
        )

    db.query(Adjudicacion).filter_by(licitacion_id=existing.id).delete()
    for a in extracted["adjudicaciones"]:
        rut_n = normalizar_rut(a.get("rut"))
        prov = None
        if rut_n:
            prov = db.query(Proveedor).filter_by(rut=rut_n).one_or_none()
            if prov is None:
                prov = Proveedor(rut=rut_n, nombre=a.get("nombre"))
                db.add(prov)
                db.flush()
            elif a.get("nombre") and not prov.nombre:
                prov.nombre = a.get("nombre")
        db.add(
            Adjudicacion(
                licitacion_id=existing.id,
                proveedor_id=prov.id if prov else None,
                monto=a.get("monto"),
                fecha=a.get("fecha"),
            )
        )
    db.flush()
    return status
