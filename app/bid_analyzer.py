"""app/bid_analyzer.py — Motor estadístico Monte Carlo para análisis de propuestas."""
from __future__ import annotations
import math, random, statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.database import get_db
from app.models import LicitacionSnapshot


@dataclass
class PrecioEstimado:
    precio_base: int; precio_minimo: int; precio_maximo: int
    ic_95_bajo: int; ic_95_alto: int; desviacion: float; n_muestras: int; confianza: str


@dataclass
class BidOptimo:
    precio_optimo: int; margen_pct: float; probabilidad_ganar: float
    rango_agresivo: Tuple[int, int]; rango_conservador: Tuple[int, int]


@dataclass
class PerfilOrganismo:
    nombre: str; total_licitaciones: int; monto_promedio: Optional[float]
    ratio_adj_promedio: Optional[float]; competitividad: str


@dataclass
class AnalisisRiesgo:
    nivel: str; score: int; factores: List[Dict[str, str]]


@dataclass
class AnalisisPropuesta:
    licitacion_id: int; codigo: str; titulo: str; monto_estimado: int
    precio: PrecioEstimado; bid_optimo: BidOptimo; organismo: PerfilOrganismo
    riesgo: AnalisisRiesgo; score_oportunidad: int; veredicto: str
    justificacion: str; similares: List[Dict]; generado_en: datetime = field(default_factory=datetime.utcnow)
    disclaimer: str = (
        "Análisis estadístico orientativo basado en datos históricos de Mercado Público. "
        "NO constituye predicción de adjudicación ni consejo de oferta. "
        "La decisión final es siempre del usuario."
    )


class BidAnalyzer:
    N_SIM = 5000

    def analizar(self, snap_id: int, costo_propio: Optional[int] = None) -> Optional[AnalisisPropuesta]:
        with get_db() as db:
            snap = db.query(LicitacionSnapshot).filter_by(id=snap_id).first()
            if not snap:
                return None
            datos = snap.datos or {}
            codigo = snap.codigo
            titulo = datos.get("titulo") or ""
            monto = snap.monto_clp or 0
            organismo_nombre = datos.get("organismo") or datos.get("nombre_organismo") or ""
            org_codigo = datos.get("codigo_organismo")
            fecha_cierre_str = datos.get("fecha_cierre")

            similares_raw = self._buscar_similares(db, snap, 40)
            similares_org = self._buscar_por_organismo(db, org_codigo or organismo_nombre, 100)

            precio   = self._calcular_precio(monto, similares_raw)
            bid_opt  = self._optimizar_bid(precio, costo_propio, monto)
            perfil   = self._perfil_organismo(organismo_nombre, similares_org)
            riesgo   = self._calcular_riesgo(titulo, monto, fecha_cierre_str, perfil, precio)
            score    = self._score_oportunidad(precio, bid_opt, perfil, riesgo)
            veredicto, justif = self._veredicto(score, riesgo, precio, bid_opt)
            return AnalisisPropuesta(
                licitacion_id=snap_id, codigo=codigo, titulo=titulo, monto_estimado=monto,
                precio=precio, bid_optimo=bid_opt, organismo=perfil, riesgo=riesgo,
                score_oportunidad=score, veredicto=veredicto, justificacion=justif,
                similares=[{"codigo":s["codigo"],"titulo":s["titulo"][:70],"monto":s["monto"],"estado":s["estado"],"ratio":s.get("ratio")} for s in similares_raw[:8]],
            )

    def _calcular_precio(self, monto: int, similares: List[Dict]) -> PrecioEstimado:
        montos = [s["monto"] for s in similares if s.get("monto")]
        if len(montos) >= 3:
            base = int(statistics.median(montos))
            std = statistics.stdev(montos) if len(montos) > 1 else base * 0.15
            conf = "alta" if len(montos) >= 15 else ("media" if len(montos) >= 5 else "baja")
        elif monto:
            base = monto; std = monto * 0.2; conf = "baja"
        else:
            base = 1_000_000; std = 200_000; conf = "muy baja"
        samples = [max(0, int(base + std * self._normal_sample())) for _ in range(self.N_SIM)]
        samples.sort()
        return PrecioEstimado(
            precio_base=base, precio_minimo=samples[int(0.05*self.N_SIM)],
            precio_maximo=samples[int(0.95*self.N_SIM)],
            ic_95_bajo=samples[int(0.025*self.N_SIM)], ic_95_alto=samples[int(0.975*self.N_SIM)],
            desviacion=float(std), n_muestras=len(montos), confianza=conf,
        )

    def _optimizar_bid(self, precio: PrecioEstimado, costo: Optional[int], monto_ref: int) -> BidOptimo:
        base = precio.precio_base
        costo = costo or int(base * 0.75)
        opt = max(costo + 1, int(base * 0.92))
        margen = (opt - costo) / opt * 100 if opt else 0
        # Heurística simple de probabilidad
        if opt <= precio.ic_95_bajo:
            p_win = 0.65
        elif opt <= base:
            p_win = 0.45
        elif opt <= precio.ic_95_alto:
            p_win = 0.25
        else:
            p_win = 0.10
        return BidOptimo(
            precio_optimo=opt, margen_pct=round(margen, 1), probabilidad_ganar=p_win,
            rango_agresivo=(int(base*0.85), int(base*0.95)),
            rango_conservador=(int(base*0.95), int(base*1.05)),
        )

    def _perfil_organismo(self, nombre: str, similares: List[Dict]) -> PerfilOrganismo:
        montos = [s["monto"] for s in similares if s.get("monto")]
        n = len(similares)
        prom = statistics.mean(montos) if montos else None
        if n >= 20:
            comp = "alta"
        elif n >= 5:
            comp = "media"
        else:
            comp = "baja / datos insuficientes"
        return PerfilOrganismo(
            nombre=nombre or "Desconocido", total_licitaciones=n,
            monto_promedio=prom, ratio_adj_promedio=None, competitividad=comp,
        )

    def _calcular_riesgo(self, titulo, monto, fecha_cierre, perfil, precio) -> AnalisisRiesgo:
        factores = []
        score = 30
        if precio.confianza in ("baja", "muy baja"):
            factores.append({"nombre": "Pocos datos históricos", "detalle": f"Confianza {precio.confianza}"})
            score += 20
        if perfil.total_licitaciones < 5:
            factores.append({"nombre": "Organismo poco conocido en BD", "detalle": f"{perfil.total_licitaciones} registros"})
            score += 15
        if monto and monto > 500_000_000:
            factores.append({"nombre": "Monto elevado", "detalle": f"${monto:,.0f}"})
            score += 10
        if not factores:
            factores.append({"nombre": "Sin factores críticos detectados", "detalle": ""})
        nivel = "alto" if score >= 60 else ("medio" if score >= 40 else "bajo")
        return AnalisisRiesgo(nivel=nivel, score=min(score, 100), factores=factores)

    def _score_oportunidad(self, precio, bid, perfil, riesgo) -> int:
        s = 50
        if precio.confianza == "alta":
            s += 15
        elif precio.confianza == "media":
            s += 8
        s += int(bid.probabilidad_ganar * 30)
        s -= max(0, riesgo.score - 40) // 2
        return max(0, min(100, s))

    def _veredicto(self, score, riesgo, precio, bid):
        if score >= 70 and riesgo.nivel != "alto":
            return "✅ Oportunidad atractiva", f"Score {score}/100. Precio sugerido: ${bid.precio_optimo:,.0f} CLP."
        if score >= 45:
            return "⚠️  Evaluar", f"Factores mixtos (score {score}/100). Revisar riesgos. Precio sugerido: ${bid.precio_optimo:,.0f} CLP."
        return "❌ Descartar", f"Score bajo ({score}/100) con riesgo {riesgo.nivel}. Considera otras licitaciones."

    def _buscar_similares(self, db, snap, limit):
        monto = snap.monto_clp or 0; region = snap.region
        q = db.query(LicitacionSnapshot).filter(LicitacionSnapshot.id != snap.id, LicitacionSnapshot.monto_clp.isnot(None))
        if region:
            q = q.filter(LicitacionSnapshot.region == region)
        if monto:
            q = q.filter(LicitacionSnapshot.monto_clp >= int(monto*0.2), LicitacionSnapshot.monto_clp <= int(monto*5.0))
        return [{"codigo":s.codigo,"titulo":(s.datos or {}).get("titulo",""),"monto":s.monto_clp,"estado":s.estado or "","ratio":None} for s in q.limit(limit).all()]

    def _buscar_por_organismo(self, db, org, limit):
        from sqlalchemy import cast, String
        if not org:
            return []
        org_str = str(org)[:20]
        q = db.query(LicitacionSnapshot).filter(
            LicitacionSnapshot.monto_clp.isnot(None),
            cast(LicitacionSnapshot.datos["organismo"], String).ilike(f"%{org_str}%"),
        ).limit(limit)
        return [{"monto": s.monto_clp, "estado": s.estado or "", "ratio": None} for s in q.all()]

    @staticmethod
    def _normal_sample():
        u1 = max(1e-10, random.random()); u2 = random.random()
        return math.sqrt(-2*math.log(u1)) * math.cos(2*math.pi*u2)


bid_analyzer = BidAnalyzer()
