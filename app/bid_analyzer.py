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
    ic_95_bajo: int; ic_95_alto: int; ratio_historico: float
    n_muestra: int; confianza: str

@dataclass
class BidOptimo:
    precio_optimo: int; margen_sugerido: float; prob_ganar: float
    utilidad_esperada: int; curva_precios: List[Dict]

@dataclass
class PerfilOrganismo:
    nombre: str; total_licitaciones: int; monto_promedio: int
    ratio_adj_promedio: float; categorias_frecuentes: List[str]
    plazo_promedio_dias: int; score_pagador: int

@dataclass
class RiskScore:
    score: int; nivel: str; factores: List[Dict]; recomendacion: str

@dataclass
class AnalisisPropuesta:
    licitacion_id: int; codigo: str; titulo: str; monto_estimado: Optional[int]
    precio: PrecioEstimado; bid_optimo: BidOptimo; organismo: PerfilOrganismo
    riesgo: RiskScore; score_oportunidad: int; veredicto: str
    justificacion: str; similares: List[Dict]; generado_en: str


class BidAnalyzer:
    _RATIO_DEFAULT = 0.87; _RATIO_SIGMA = 0.12; _N_MONTE_CARLO = 10_000; _COMPETIDORES_EST = 4

    def analizar(self, snap_id: int, costo_propio: Optional[int] = None) -> AnalisisPropuesta:
        with get_db() as db:
            snap = db.query(LicitacionSnapshot).filter_by(id=snap_id).first()
            if not snap: raise ValueError(f"Snapshot {snap_id} no encontrado")
            datos = snap.datos or {}
            codigo = snap.codigo; titulo = datos.get("titulo", "")
            monto = snap.monto_clp
            organismo_nombre = datos.get("organismo", "Desconocido")
            org_codigo = datos.get("codigo_organismo", "")
            fecha_cierre_str = datos.get("fecha_cierre")
            similares_raw = self._buscar_similares(db, snap, 200)
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
            generado_en=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def _calcular_precio(self, monto, similares):
        ratios = [s["ratio"] for s in similares if s.get("ratio") and 0.3 < s["ratio"] < 1.5]
        if len(ratios) >= 5:
            ratio_mean = statistics.mean(ratios)
            ratio_sigma = statistics.stdev(ratios) if len(ratios) > 1 else self._RATIO_SIGMA
            confianza = "alta" if len(ratios) >= 30 else "media"
        else:
            ratio_mean = self._RATIO_DEFAULT; ratio_sigma = self._RATIO_SIGMA; confianza = "baja"
        base = monto or 0
        precios_sim = sorted([int(base * max(0.2, min(1.4, ratio_mean + ratio_sigma * self._normal_sample()))) for _ in range(1000)]) if base else []
        def pct(p): return precios_sim[max(0,min(int(len(precios_sim)*p/100),len(precios_sim)-1))] if precios_sim else int(base*ratio_mean)
        return PrecioEstimado(
            precio_base=int(base*ratio_mean), precio_minimo=pct(10), precio_maximo=pct(90),
            ic_95_bajo=int(base*max(0.3,ratio_mean-1.96*ratio_sigma)),
            ic_95_alto=int(base*min(1.3,ratio_mean+1.96*ratio_sigma)),
            ratio_historico=round(ratio_mean,3), n_muestra=len(ratios), confianza=confianza,
        )

    def _optimizar_bid(self, precio, costo_propio, monto_estimado):
        base = monto_estimado or precio.precio_base or 1
        costo = costo_propio or int(base * 0.60)
        lo = max(int(base*0.30), costo); hi = int(base*1.05)
        curva = []; best_u = -1; best_p = precio.precio_base; best_prob = 0.0
        for pb in range(lo, hi, max(1,(hi-lo)//50)):
            prob = max(0.0, min(1.0, (hi-pb)/(hi-lo))) ** self._COMPETIDORES_EST
            u_esp = int((pb-costo)*prob)
            curva.append({"precio":pb,"prob_win":round(prob,3),"utilidad":u_esp,"margen":round((pb-costo)/pb,3) if pb>0 else 0})
            if u_esp > best_u: best_u=u_esp; best_p=pb; best_prob=prob
        margen = (best_p-costo)/best_p if best_p>0 else 0
        return BidOptimo(precio_optimo=best_p, margen_sugerido=round(margen,3),
            prob_ganar=round(best_prob,3), utilidad_esperada=best_u,
            curva_precios=curva[::max(1,len(curva)//20)])

    def _perfil_organismo(self, nombre, historial):
        n = len(historial)
        montos = [h["monto"] for h in historial if h.get("monto")]
        ratios = [h["ratio"] for h in historial if h.get("ratio") and 0.3 < h["ratio"] < 1.3]
        monto_prom = int(statistics.mean(montos)) if montos else 0
        ratio_prom = round(statistics.mean(ratios),3) if ratios else self._RATIO_DEFAULT
        score_pagador = min(100, int((min(n,50)/50)*40 + (1-abs(ratio_prom-0.90))*40 + 20))
        return PerfilOrganismo(nombre=nombre, total_licitaciones=n, monto_promedio=monto_prom,
            ratio_adj_promedio=ratio_prom, categorias_frecuentes=[],
            plazo_promedio_dias=21, score_pagador=score_pagador)

    def _calcular_riesgo(self, titulo, monto, fecha_cierre, perfil, precio):
        factores = []; score = 0
        if fecha_cierre:
            try:
                fc = datetime.strptime(fecha_cierre[:10], "%Y-%m-%d")
                dias = (fc - datetime.now()).days
                if dias < 5: factores.append({"nombre":"Plazo crítico","impacto":25,"detalle":f"Cierre en {dias} días"}); score+=25
                elif dias < 10: factores.append({"nombre":"Plazo ajustado","impacto":12,"detalle":f"Cierre en {dias} días"}); score+=12
            except: pass
        if monto:
            if monto < 500_000: factores.append({"nombre":"Monto muy bajo","impacto":15,"detalle":"<$500K"}); score+=15
            elif monto > 500_000_000: factores.append({"nombre":"Monto muy alto","impacto":20,"detalle":">$500M"}); score+=20
        else:
            factores.append({"nombre":"Monto desconocido","impacto":15,"detalle":"Sin monto estimado"}); score+=15
        if precio.n_muestra < 5: factores.append({"nombre":"Pocos datos históricos","impacto":15,"detalle":f"n={precio.n_muestra}"}); score+=15
        elif precio.n_muestra < 15: factores.append({"nombre":"Datos limitados","impacto":8,"detalle":f"n={precio.n_muestra}"}); score+=8
        if perfil.score_pagador < 40: factores.append({"nombre":"Organismo poco conocido","impacto":15,"detalle":"Historial limitado"}); score+=15
        for p in ["urgente","urgencia","emergencia"]:
            if p in (titulo or "").lower(): factores.append({"nombre":f"Keyword: '{p}'","impacto":10,"detalle":"Condiciones más restrictivas"}); score+=10; break
        score = min(100, score)
        nivel = "bajo" if score<25 else "medio" if score<50 else "alto" if score<75 else "crítico"
        recs = {"bajo":"Proceder con propuesta estándar.","medio":"Revisar factores antes de presentar.","alto":"Evaluar con cuidado si tienes los recursos.","crítico":"Alto riesgo — participar solo con ventaja muy clara."}
        return RiskScore(score=score, nivel=nivel, factores=factores or [{"nombre":"Sin factores de riesgo","impacto":0,"detalle":""}], recomendacion=recs[nivel])

    def _score_oportunidad(self, precio, bid, perfil, riesgo):
        return min(100, int(
            bid.prob_ganar*100*0.30 + min(bid.margen_sugerido*2,1.0)*100*0.25 +
            {"alta":100,"media":65,"baja":30}.get(precio.confianza,30)*0.25 +
            (100-riesgo.score)*0.20
        ))

    def _veredicto(self, score, riesgo, precio, bid):
        if score >= 65 and riesgo.nivel in ("bajo","medio"):
            return "✅ Participar", f"Oportunidad sólida (score {score}/100). Precio óptimo: ${bid.precio_optimo:,.0f} CLP · P(ganar) {bid.prob_ganar:.0%} · Margen {bid.margen_sugerido:.0%}."
        elif score >= 40 or riesgo.nivel == "medio":
            return "⚠️  Evaluar", f"Factores mixtos (score {score}/100). Revisar riesgos. Precio sugerido: ${bid.precio_optimo:,.0f} CLP."
        return "❌ Descartar", f"Score bajo ({score}/100) con riesgo {riesgo.nivel}. Considera otras licitaciones."

    def _buscar_similares(self, db, snap, limit):
        monto = snap.monto_clp or 0; region = snap.region
        q = db.query(LicitacionSnapshot).filter(LicitacionSnapshot.id != snap.id, LicitacionSnapshot.monto_clp.isnot(None))
        if region: q = q.filter(LicitacionSnapshot.region == region)
        if monto: q = q.filter(LicitacionSnapshot.monto_clp >= int(monto*0.2), LicitacionSnapshot.monto_clp <= int(monto*5.0))
        return [{"codigo":s.codigo,"titulo":(s.datos or {}).get("titulo",""),"monto":s.monto_clp,"estado":s.estado or "","ratio":None} for s in q.limit(limit).all()]

    def _buscar_por_organismo(self, db, org, limit):
        from sqlalchemy import cast, String
        q = db.query(LicitacionSnapshot).filter(LicitacionSnapshot.monto_clp.isnot(None), cast(LicitacionSnapshot.datos["organismo"],String).ilike(f"%{org[:20]}%")).limit(limit)
        return [{"monto":s.monto_clp,"estado":s.estado or "","ratio":None} for s in q.all()]

    @staticmethod
    def _normal_sample():
        u1 = max(1e-10, random.random()); u2 = random.random()
        return math.sqrt(-2*math.log(u1)) * math.cos(2*math.pi*u2)


bid_analyzer = BidAnalyzer()
