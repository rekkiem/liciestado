"""app/analytics.py — KPIs y métricas sobre licitaciones_snapshot."""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import cast, String, func
from app.database import get_db
from app.models import LicitacionSnapshot, AlertaGenerada, ReglaUsuario

REGIONES_CHILE: Dict[int, str] = {
    1:"Tarapacá",2:"Antofagasta",3:"Atacama",4:"Coquimbo",5:"Valparaíso",
    6:"O'Higgins",7:"Maule",8:"Biobío",9:"Araucanía",10:"Los Lagos",
    11:"Aysén",12:"Magallanes",13:"Metropolitana",14:"Los Ríos",
    15:"Arica y Parinacota",16:"Ñuble",
}

class AnalyticsEngine:
    def _cutoff(self, dias: int) -> datetime:
        return datetime.utcnow() - timedelta(days=dias)

    def resumen_ejecutivo(self, dias: int = 30) -> Dict:
        corte = self._cutoff(dias)
        with get_db() as db:
            total = db.query(func.count(LicitacionSnapshot.id)).scalar() or 0
            monto_total = db.query(func.sum(LicitacionSnapshot.monto_clp)).filter(
                LicitacionSnapshot.monto_clp.isnot(None),
                LicitacionSnapshot.fecha_sincronizacion >= corte
            ).scalar() or 0
            monto_prom = db.query(func.avg(LicitacionSnapshot.monto_clp)).filter(
                LicitacionSnapshot.monto_clp.isnot(None),
                LicitacionSnapshot.fecha_sincronizacion >= corte
            ).scalar() or 0
            organismos = db.query(func.count(func.distinct(
                cast(LicitacionSnapshot.datos["organismo"], String)
            ))).filter(LicitacionSnapshot.fecha_sincronizacion >= corte).scalar() or 0
            regiones = db.query(func.count(func.distinct(LicitacionSnapshot.region))).filter(
                LicitacionSnapshot.region.isnot(None),
                LicitacionSnapshot.fecha_sincronizacion >= corte
            ).scalar() or 0
            alertas = db.query(func.count(AlertaGenerada.id)).scalar() or 0
            reglas  = db.query(func.count(ReglaUsuario.id)).filter_by(activa=True).scalar() or 0
        return {
            "total_entidades": total, "monto_total_clp": int(monto_total),
            "monto_promedio_clp": int(monto_prom), "organismos_unicos": organismos,
            "regiones_activas": regiones, "total_alertas": alertas, "reglas_activas": reglas,
        }

    def top_categorias(self, limit: int = 12, dias: int = 30) -> List[Dict]:
        corte = self._cutoff(dias)
        with get_db() as db:
            rows = db.query(
                cast(LicitacionSnapshot.datos["codigo_producto"], String),
                func.count(LicitacionSnapshot.id),
                func.sum(LicitacionSnapshot.monto_clp),
            ).filter(LicitacionSnapshot.fecha_sincronizacion >= corte).group_by(
                cast(LicitacionSnapshot.datos["codigo_producto"], String)
            ).order_by(func.count(LicitacionSnapshot.id).desc()).limit(limit).all()
        return [{"codigo": r[0], "nombre": r[0] or "Sin categoría", "cantidad": r[1] or 0, "monto_total": r[2] or 0} for r in rows]

    def top_organismos(self, limit: int = 12, dias: int = 30) -> List[Dict]:
        corte = self._cutoff(dias)
        with get_db() as db:
            rows = db.query(
                cast(LicitacionSnapshot.datos["organismo"], String),
                func.count(LicitacionSnapshot.id),
                func.sum(LicitacionSnapshot.monto_clp),
            ).filter(LicitacionSnapshot.fecha_sincronizacion >= corte,
                     cast(LicitacionSnapshot.datos["organismo"], String).isnot(None)
            ).group_by(cast(LicitacionSnapshot.datos["organismo"], String)
            ).order_by(func.count(LicitacionSnapshot.id).desc()).limit(limit).all()
        return [{"organismo": (r[0] or "").strip('"'), "cantidad": r[1] or 0, "monto_total": r[2] or 0} for r in rows if r[0]]

    def distribucion_regional(self, dias: int = 30) -> List[Dict]:
        corte = self._cutoff(dias)
        with get_db() as db:
            rows = db.query(LicitacionSnapshot.region, func.count(LicitacionSnapshot.id),
                            func.sum(LicitacionSnapshot.monto_clp),
            ).filter(LicitacionSnapshot.region.isnot(None),
                     LicitacionSnapshot.fecha_sincronizacion >= corte
            ).group_by(LicitacionSnapshot.region
            ).order_by(func.count(LicitacionSnapshot.id).desc()).all()
        return [{"region": r[0], "nombre_region": REGIONES_CHILE.get(r[0], f"R{r[0]}"), "cantidad": r[1] or 0, "monto_total": r[2] or 0} for r in rows]

    def tendencia_temporal(self, dias: int = 30) -> List[Dict]:
        corte = self._cutoff(dias)
        with get_db() as db:
            rows = db.query(
                func.strftime("%Y-%m", LicitacionSnapshot.fecha_publicacion).label("periodo"),
                func.count(LicitacionSnapshot.id),
                func.sum(LicitacionSnapshot.monto_clp),
            ).filter(LicitacionSnapshot.fecha_publicacion.isnot(None),
                     LicitacionSnapshot.fecha_publicacion >= corte
            ).group_by("periodo").order_by("periodo").all()
        return [{"periodo": r[0] or "?", "cantidad": r[1] or 0, "monto_total": r[2] or 0} for r in rows]

    def actividad_diaria(self, dias: int = 30) -> List[Dict]:
        corte = self._cutoff(dias)
        with get_db() as db:
            rows = db.query(
                func.strftime("%Y-%m-%d", LicitacionSnapshot.fecha_sincronizacion).label("fecha"),
                func.count(LicitacionSnapshot.id),
            ).filter(LicitacionSnapshot.fecha_sincronizacion >= corte
            ).group_by("fecha").order_by("fecha").all()
        return [{"fecha": r[0] or "?", "cantidad": r[1] or 0} for r in rows]
