"""
app/dashboard/routes.py — Dashboard multi-tenant.

Todas las rutas requieren login (Flask-Login).
Todas las consultas filtran por current_user.id.
"""
import csv
import io
import json as _json
import logging
from datetime import datetime as _dt
from functools import wraps

from flask import (
    Blueprint, abort, jsonify, redirect, render_template,
    request, url_for, Response,
)
from flask_login import login_required, current_user
from sqlalchemy import cast, String, func

from app.analytics import AnalyticsEngine, REGIONES_CHILE
from app.database import get_db
from app.models import ReglaUsuario, AlertaGenerada, LicitacionSnapshot
from app.filter_engine import validar_filtros, FILTROS_VALIDOS, describe_filtros
from app.scheduler import ejecutar_regla_manualmente

logger = logging.getLogger(__name__)
bp = Blueprint("dashboard", __name__)

# Alias para backward compat con decoradores @requires_auth
requires_auth = login_required
analytics = AnalyticsEngine()


def _u() -> int:
    """Shorthand: ID del usuario actual."""
    return current_user.id


def _check_ticket():
    """Retorna True si el usuario tiene ticket configurado."""
    from app.auth import obtener_ticket_plano
    return bool(obtener_ticket_plano(_u()))


# ═══════════════════════════════════════════════════════════════════════════════
# HOME — listado de reglas
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/dashboard")
@login_required
def home():
    tiene_ticket = _check_ticket()
    with get_db() as db:
        reglas_q = db.query(ReglaUsuario).filter_by(user_id=_u()).order_by(
            ReglaUsuario.fecha_creacion.desc()
        ).all()

        alertas_recientes = (
            db.query(AlertaGenerada)
            .filter_by(user_id=_u())
            .order_by(AlertaGenerada.fecha_alerta.desc())
            .limit(5)
            .all()
        )

        reglas_data = []
        for r in reglas_q:
            n_alertas = db.query(func.count(AlertaGenerada.id)).filter_by(
                regla_id=r.id).scalar() or 0
            reglas_data.append({
                "id": r.id, "nombre": r.nombre_regla, "activa": r.activa,
                "tipo": r.tipo_entidad, "filtros": r.filtros,
                "email": r.email_destino,
                "fecha_creacion": r.fecha_creacion,
                "fecha_ult_exec": r.fecha_ultima_ejecucion,
                "n_alertas": n_alertas,
                "filtros_desc": describe_filtros(r.filtros) if r.filtros else "Sin filtros",
            })

        alertas_data = []
        for a in alertas_recientes:
            d = a.datos_resumen or {}
            alertas_data.append({
                "id": a.id, "regla_id": a.regla_id,
                "regla_nombre": a.regla.nombre_regla if a.regla else "—",
                "titulo": d.get("titulo", a.entidad_id),
                "codigo": a.entidad_id,
                "monto_clp": d.get("monto_clp"),
                "fecha_alerta": a.fecha_alerta,
                "enviado_email": a.enviado_email,
                "tipo": d.get("tipo", "licitacion"),
            })

    return render_template(
        "index.html",
        reglas=reglas_data,
        alertas_recientes=alertas_data,
        tiene_ticket=tiene_ticket,
        limite_reglas=current_user.limite_reglas,
        es_pro=current_user.es_pro,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# REGLAS — CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/reglas/nueva", methods=["GET", "POST"])
@login_required
def regla_nueva():
    with get_db() as db:
        n_reglas = db.query(func.count(ReglaUsuario.id)).filter_by(user_id=_u()).scalar() or 0

    if n_reglas >= current_user.limite_reglas:
        return render_template(
            "regla_form.html", regla=None, form_data={},
            regiones=REGIONES_CHILE, error_limite=True,
            es_pro=current_user.es_pro,
        )

    if request.method == "POST":
        return _guardar_regla(None)

    return render_template(
        "regla_form.html", regla=None, form_data={},
        regiones=REGIONES_CHILE, es_pro=current_user.es_pro,
    )


@bp.route("/reglas/<int:regla_id>/editar", methods=["GET", "POST"])
@login_required
def regla_editar(regla_id: int):
    with get_db() as db:
        regla = db.query(ReglaUsuario).filter_by(id=regla_id, user_id=_u()).first()
        if not regla:
            abort(404)
        data = {
            "id": regla.id, "nombre": regla.nombre_regla, "activa": regla.activa,
            "tipo": regla.tipo_entidad, "filtros": regla.filtros,
            "email": regla.email_destino,
        }

    if request.method == "POST":
        return _guardar_regla(regla_id)

    return render_template(
        "regla_form.html", regla=data, form_data=data,
        regiones=REGIONES_CHILE, es_pro=current_user.es_pro,
    )


def _guardar_regla(regla_id):
    nombre   = request.form.get("nombre_regla", "").strip()
    tipo     = request.form.get("tipo_entidad", "licitacion")
    email    = request.form.get("email_destino", current_user.email).strip()
    activa   = request.form.get("activa") != "0"
    filtros_raw = request.form.get("filtros_json", "{}")

    if not nombre:
        flash("El nombre es obligatorio.", "error")
        return redirect(request.url)

    try:
        filtros = _json.loads(filtros_raw) if filtros_raw.strip() else {}
    except _json.JSONDecodeError:
        flash("El JSON de filtros no es válido.", "error")
        return redirect(request.url)

    errores = validar_filtros(filtros)
    if errores:
        flash(f"Filtros inválidos: {'; '.join(errores)}", "error")
        return redirect(request.url)

    with get_db() as db:
        if regla_id:
            r = db.query(ReglaUsuario).filter_by(id=regla_id, user_id=_u()).first()
            if not r:
                abort(404)
            r.nombre_regla = nombre; r.tipo_entidad = tipo
            r.email_destino = email; r.filtros = filtros; r.activa = activa
            msg = "Regla actualizada."
        else:
            r = ReglaUsuario(
                user_id=_u(), nombre_regla=nombre, tipo_entidad=tipo,
                email_destino=email, filtros=filtros, activa=activa,
            )
            db.add(r)
            msg = "Regla creada."

    flash(msg, "success")
    return redirect(url_for("dashboard.home"))


@bp.route("/reglas/<int:regla_id>/toggle", methods=["POST"])
@login_required
def regla_toggle(regla_id: int):
    with get_db() as db:
        r = db.query(ReglaUsuario).filter_by(id=regla_id, user_id=_u()).first()
        if not r:
            abort(404)
        r.activa = not r.activa
        estado = "activada" if r.activa else "desactivada"
    flash(f"Regla {estado}.", "success")
    return redirect(url_for("dashboard.home"))


@bp.route("/reglas/<int:regla_id>/eliminar", methods=["POST"])
@login_required
def regla_eliminar(regla_id: int):
    with get_db() as db:
        r = db.query(ReglaUsuario).filter_by(id=regla_id, user_id=_u()).first()
        if not r:
            abort(404)
        db.delete(r)
    flash("Regla eliminada.", "success")
    return redirect(url_for("dashboard.home"))


@bp.route("/reglas/<int:regla_id>/run", methods=["POST"])
@login_required
def regla_run(regla_id: int):
    with get_db() as db:
        r = db.query(ReglaUsuario).filter_by(id=regla_id, user_id=_u()).first()
        if not r:
            abort(404)

    from app.auth import obtener_ticket_plano
    ticket = obtener_ticket_plano(_u())
    if not ticket:
        flash("Debes configurar tu ticket de Mercado Público antes de ejecutar reglas.", "error")
        return redirect(url_for("auth.configuracion"))

    stats = ejecutar_regla_manualmente(regla_id, ticket_override=ticket)
    n = stats.get("alertas_nuevas", stats.get("alertas_generadas", 0))
    flash(f"Regla ejecutada: {n} alertas nuevas.", "success" if n > 0 else "info")
    return redirect(url_for("dashboard.home"))


# ═══════════════════════════════════════════════════════════════════════════════
# ALERTAS
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/alertas")
@login_required
def alertas():
    page         = request.args.get("page", 1, type=int)
    per_page     = 30
    tipo_filtro  = request.args.get("tipo", "").strip()
    regla_filtro = request.args.get("regla", "").strip()

    with get_db() as db:
        q = db.query(AlertaGenerada).filter_by(user_id=_u())
        if tipo_filtro:
            q = q.filter(cast(AlertaGenerada.datos_resumen["tipo"], String) == tipo_filtro)
        if regla_filtro:
            try:
                q = q.filter(AlertaGenerada.regla_id == int(regla_filtro))
            except ValueError:
                pass

        total    = q.count()
        alertas_ = q.order_by(AlertaGenerada.fecha_alerta.desc()).offset(
            (page - 1) * per_page).limit(per_page).all()

        reglas_sel = db.query(ReglaUsuario.id, ReglaUsuario.nombre_regla).filter_by(
            user_id=_u()).all()

        alertas_data = []
        for a in alertas_:
            d = a.datos_resumen or {}
            alertas_data.append({
                "id": a.id, "regla_id": a.regla_id,
                "regla_nombre": a.regla.nombre_regla if a.regla else "—",
                "entidad_id": a.entidad_id,
                "titulo": d.get("titulo", a.entidad_id),
                "monto_clp": d.get("monto_clp"),
                "region": d.get("region"),
                "nombre_region": d.get("nombre_region"),
                "organismo": d.get("organismo"),
                "tipo": d.get("tipo", "licitacion"),
                "codigo": d.get("codigo", a.entidad_id),
                "fecha_alerta": a.fecha_alerta,
                "enviado_email": a.enviado_email,
                "link_detalle": d.get("link_detalle"),
            })

        reglas_select_data = [{"id": r[0], "nombre": r[1]} for r in reglas_sel]

    return render_template(
        "alertas.html",
        alertas=alertas_data, page=page,
        total=total, total_paginas=max(1, (total + per_page - 1) // per_page),
        per_page=per_page, tipo_filtro=tipo_filtro, regla_filtro=regla_filtro,
        reglas_select=reglas_select_data,
    )


@bp.route("/alertas/<int:alerta_id>")
@login_required
def alerta_detalle(alerta_id: int):
    with get_db() as db:
        a = db.query(AlertaGenerada).filter_by(id=alerta_id, user_id=_u()).first()
        if not a:
            abort(404)
        a.mostrado_dashboard = True
        data = {
            "id": a.id, "regla_id": a.regla_id,
            "regla_nombre": a.regla.nombre_regla if a.regla else "—",
            "tipo": a.datos_resumen.get("tipo", ""),
            "codigo": a.entidad_id, "datos": a.datos_resumen,
            "fecha_alerta": a.fecha_alerta, "enviado_email": a.enviado_email,
        }
    return render_template("alerta_detalle.html", alerta=data)


# ═══════════════════════════════════════════════════════════════════════════════
# LICITACIONES BROWSER
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/licitaciones")
@login_required
def licitaciones_browser():
    page     = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("pp", 50, type=int), 200)
    q        = request.args.get("q", "").strip()
    f_tipo   = request.args.get("tipo", "").strip()
    f_estado = request.args.get("estado", "").strip()
    f_region = request.args.get("region", "").strip()
    f_mmin   = request.args.get("mmin", "").strip()
    f_mmax   = request.args.get("mmax", "").strip()
    f_fd     = request.args.get("fd", "").strip()
    f_fh     = request.args.get("fh", "").strip()
    f_enr    = request.args.get("enr", "").strip()
    orden    = request.args.get("orden", "sinc_desc")
    f_org    = request.args.get("org", "").strip()

    with get_db() as db:
        base_q = db.query(LicitacionSnapshot)
        if f_tipo:   base_q = base_q.filter(LicitacionSnapshot.tipo == f_tipo)
        if f_estado: base_q = base_q.filter(LicitacionSnapshot.estado == f_estado)
        if f_region:
            try: base_q = base_q.filter(LicitacionSnapshot.region == int(f_region))
            except ValueError: pass
        if f_mmin:
            try: base_q = base_q.filter(LicitacionSnapshot.monto_clp >= int(f_mmin))
            except ValueError: pass
        if f_mmax:
            try: base_q = base_q.filter(LicitacionSnapshot.monto_clp <= int(f_mmax))
            except ValueError: pass
        if f_fd:
            try: base_q = base_q.filter(LicitacionSnapshot.fecha_publicacion >= _dt.strptime(f_fd, "%Y-%m-%d"))
            except ValueError: pass
        if f_fh:
            try: base_q = base_q.filter(LicitacionSnapshot.fecha_publicacion <= _dt.strptime(f_fh, "%Y-%m-%d"))
            except ValueError: pass
        if f_enr == "si": base_q = base_q.filter(LicitacionSnapshot.region.isnot(None))
        elif f_enr == "no": base_q = base_q.filter(LicitacionSnapshot.region.is_(None))
        if q:
            like = f"%{q}%"
            base_q = base_q.filter(
                LicitacionSnapshot.codigo.ilike(like) |
                cast(LicitacionSnapshot.datos["titulo"], String).ilike(like) |
                cast(LicitacionSnapshot.datos["organismo"], String).ilike(like)
            )
        if f_org:
            base_q = base_q.filter(
                cast(LicitacionSnapshot.datos["organismo"], String).ilike(f"%{f_org}%"))

        orden_map = {
            "sinc_desc":  LicitacionSnapshot.fecha_sincronizacion.desc(),
            "sinc_asc":   LicitacionSnapshot.fecha_sincronizacion.asc(),
            "monto_desc": LicitacionSnapshot.monto_clp.desc().nulls_last(),
            "monto_asc":  LicitacionSnapshot.monto_clp.asc().nulls_last(),
            "fecha_desc": LicitacionSnapshot.fecha_publicacion.desc().nulls_last(),
            "titulo_asc": cast(LicitacionSnapshot.datos["titulo"], String).asc(),
        }
        base_q = base_q.order_by(orden_map.get(orden, LicitacionSnapshot.fecha_sincronizacion.desc()))
        total  = base_q.count()
        snaps  = base_q.offset((page - 1) * per_page).limit(per_page).all()

        total_all = db.query(func.count(LicitacionSnapshot.id)).scalar()
        con_datos = db.query(func.count(LicitacionSnapshot.id)).filter(
            LicitacionSnapshot.region.isnot(None)).scalar()
        monto_total = db.query(func.sum(LicitacionSnapshot.monto_clp)).filter(
            LicitacionSnapshot.monto_clp.isnot(None)).scalar() or 0
        monto_prom  = db.query(func.avg(LicitacionSnapshot.monto_clp)).filter(
            LicitacionSnapshot.monto_clp.isnot(None)).scalar() or 0

        estados_q = (db.query(LicitacionSnapshot.estado, func.count(LicitacionSnapshot.id))
                     .filter(LicitacionSnapshot.estado.isnot(None), LicitacionSnapshot.estado != "")
                     .group_by(LicitacionSnapshot.estado)
                     .order_by(func.count(LicitacionSnapshot.id).desc()).all())
        estados_opts = [(e, n) for e, n in estados_q if e]

        regiones_q = (db.query(LicitacionSnapshot.region, func.count(LicitacionSnapshot.id))
                      .filter(LicitacionSnapshot.region.isnot(None))
                      .group_by(LicitacionSnapshot.region)
                      .order_by(func.count(LicitacionSnapshot.id).desc()).all())
        regiones_opts = [(r, REGIONES_CHILE.get(r, f"R{r}"), n) for r, n in regiones_q]

        rows = []
        for s in snaps:
            d = s.datos or {}
            rows.append({
                "id": s.id, "codigo": s.codigo, "tipo": s.tipo,
                "titulo": d.get("titulo") or s.codigo,
                "organismo": d.get("organismo") or "",
                "region": s.region,
                "nombre_region": d.get("nombre_region") or REGIONES_CHILE.get(s.region, ""),
                "monto_clp": s.monto_clp, "estado": s.estado or d.get("estado") or "",
                "fecha_pub": s.fecha_publicacion.strftime("%d-%m-%Y") if s.fecha_publicacion else None,
                "fecha_cierre": d.get("fecha_cierre"),
                "fecha_sinc": s.fecha_sincronizacion.strftime("%d-%m-%Y %H:%M") if s.fecha_sincronizacion else "",
                "link": d.get("link_detalle") or "",
                "enriquecido": s.region is not None or s.monto_clp is not None,
            })

    qs_base = f"q={q}&tipo={f_tipo}&estado={f_estado}&region={f_region}&mmin={f_mmin}&mmax={f_mmax}&fd={f_fd}&fh={f_fh}&enr={f_enr}&org={f_org}&pp={per_page}&orden={orden}"
    n_filtros = sum(1 for v in [q,f_tipo,f_estado,f_region,f_mmin,f_mmax,f_fd,f_fh,f_enr,f_org] if v)
    return render_template(
        "licitaciones.html", rows=rows, page=page, per_page=per_page,
        total=total, total_paginas=max(1, (total + per_page - 1) // per_page),
        q=q, f_tipo=f_tipo, f_estado=f_estado, f_region=f_region,
        f_mmin=f_mmin, f_mmax=f_mmax, f_fd=f_fd, f_fh=f_fh, f_enr=f_enr,
        orden=orden, f_org=f_org, estados_opts=estados_opts,
        regiones_opts=regiones_opts, REGIONES_CHILE=REGIONES_CHILE,
        total_all=total_all, con_datos=con_datos, sin_datos=total_all - con_datos,
        monto_total=monto_total, monto_prom=int(monto_prom), qs_base=qs_base,
        n_filtros=n_filtros, es_pro=current_user.es_pro,
    )


@bp.route("/licitaciones/export.csv")
@login_required
def licitaciones_export_csv():
    q = request.args.get("q", "").strip()
    f_tipo = request.args.get("tipo", "").strip()
    f_estado = request.args.get("estado", "").strip()
    f_region = request.args.get("region", "").strip()
    orden = request.args.get("orden", "sinc_desc")

    with get_db() as db:
        base_q = db.query(LicitacionSnapshot)
        if f_tipo:   base_q = base_q.filter(LicitacionSnapshot.tipo == f_tipo)
        if f_estado: base_q = base_q.filter(LicitacionSnapshot.estado == f_estado)
        if f_region:
            try: base_q = base_q.filter(LicitacionSnapshot.region == int(f_region))
            except ValueError: pass
        if q:
            like = f"%{q}%"
            base_q = base_q.filter(
                LicitacionSnapshot.codigo.ilike(like) |
                cast(LicitacionSnapshot.datos["titulo"], String).ilike(like))

        orden_map = {
            "sinc_desc": LicitacionSnapshot.fecha_sincronizacion.desc(),
            "monto_desc": LicitacionSnapshot.monto_clp.desc().nulls_last(),
            "fecha_desc": LicitacionSnapshot.fecha_publicacion.desc().nulls_last(),
        }
        snaps_raw = base_q.order_by(
            orden_map.get(orden, LicitacionSnapshot.fecha_sincronizacion.desc())
        ).limit(10000).all()

        # FIX: serializar DENTRO de la sesión para evitar DetachedInstanceError
        filas_csv = []
        for s in snaps_raw:
            d = s.datos or {}
            filas_csv.append([
                s.codigo, s.tipo, d.get("titulo", ""), d.get("organismo", ""),
                s.estado or "",
                REGIONES_CHILE.get(s.region, "") if s.region else "",
                s.monto_clp or "",
                s.fecha_publicacion.strftime("%Y-%m-%d") if s.fecha_publicacion else "",
                d.get("fecha_cierre", ""),
                "Si" if s.region is not None else "No",
                d.get("link_detalle", ""),
            ])

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(["Codigo","Tipo","Titulo","Organismo","Estado",
                     "Region","Monto_CLP","Fecha_Publicacion","Fecha_Cierre",
                     "Datos_Completos","Link"])
    for fila in filas_csv:
        writer.writerow(fila)

    ts = _dt.now().strftime("%Y%m%d_%H%M")
    return Response(buf.getvalue(), mimetype="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename=licitaciones_{ts}.csv"})


@bp.route("/licitaciones/<int:snap_id>")
@login_required
def licitacion_detalle(snap_id: int):
    with get_db() as db:
        snap = db.query(LicitacionSnapshot).filter_by(id=snap_id).first()
        if not snap:
            abort(404)
        d = snap.datos or {}
        item = {
            "id": snap.id, "codigo": snap.codigo, "tipo": snap.tipo, "datos": d,
            "region": snap.region,
            "nombre_region": d.get("nombre_region") or REGIONES_CHILE.get(snap.region, ""),
            "monto_clp": snap.monto_clp, "estado": snap.estado,
            "fecha_sinc": snap.fecha_sincronizacion, "enriquecido": snap.region is not None,
        }
    return render_template("licitacion_detalle.html", item=item, REGIONES_CHILE=REGIONES_CHILE)


@bp.route("/licitaciones/<int:snap_id>/analizar")
@login_required
def licitacion_analizar(snap_id: int):
    if not current_user.es_pro:
        return render_template("pro_required.html", feature="Bid Analyzer")

    from app.bid_analyzer import bid_analyzer
    costo_str = request.args.get("costo", "").strip()
    costo = int(costo_str) if costo_str.isdigit() else None
    try:
        analisis = bid_analyzer.analizar(snap_id, costo_propio=costo)
    except ValueError:
        abort(404)
    curva_json = _json.dumps(analisis.bid_optimo.curva_precios)
    return render_template("licitacion_analisis.html",
        a=analisis, curva_json=curva_json,
        costo_input=costo or "", snap_id=snap_id)


@bp.route("/licitaciones/<int:snap_id>/analizar/json")
@login_required
def licitacion_analizar_json(snap_id: int):
    if not current_user.es_pro:
        return jsonify({"error": "Plan Pro requerido"}), 403
    from app.bid_analyzer import bid_analyzer
    import dataclasses
    costo_str = request.args.get("costo", "").strip()
    costo = int(costo_str) if costo_str.isdigit() else None
    try:
        analisis = bid_analyzer.analizar(snap_id, costo_propio=costo)
    except ValueError:
        return jsonify({"error": "Licitación no encontrada"}), 404
    def to_dict(obj):
        if dataclasses.is_dataclass(obj): return {k: to_dict(v) for k, v in dataclasses.asdict(obj).items()}
        if isinstance(obj, list): return [to_dict(i) for i in obj]
        return obj
    return jsonify(to_dict(analisis))


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/analytics")
@login_required
def analytics_dashboard():
    if not current_user.es_pro:
        return render_template("pro_required.html", feature="Analytics avanzado")
    return render_template("analytics.html", regiones=REGIONES_CHILE)


@bp.route("/api/analytics/resumen")
@login_required
def api_resumen():
    dias = request.args.get("dias", 30, type=int)
    return jsonify(analytics.resumen_ejecutivo(dias=dias))


@bp.route("/api/analytics/categorias")
@login_required
def api_categorias():
    dias  = request.args.get("dias", 30, type=int)
    limit = request.args.get("limit", 12, type=int)
    return jsonify(analytics.top_categorias(limit=limit, dias=dias))


@bp.route("/api/analytics/organismos")
@login_required
def api_organismos():
    dias  = request.args.get("dias", 30, type=int)
    limit = request.args.get("limit", 12, type=int)
    return jsonify(analytics.top_organismos(limit=limit, dias=dias))


@bp.route("/api/analytics/regional")
@login_required
def api_regional():
    dias = request.args.get("dias", 30, type=int)
    return jsonify(analytics.distribucion_regional(dias=dias))


@bp.route("/api/analytics/temporal")
@login_required
def api_temporal():
    dias = request.args.get("dias", 30, type=int)
    return jsonify(analytics.tendencia_temporal(dias=dias))


@bp.route("/api/analytics/diario")
@login_required
def api_diario():
    dias = request.args.get("dias", 30, type=int)
    return jsonify(analytics.actividad_diaria(dias=dias))


# ═══════════════════════════════════════════════════════════════════════════════
# STATUS (admin — mantiene Basic Auth)
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/api/status")
@login_required
def api_status():
    from app.scheduler import _scheduler
    with get_db() as db:
        total_snaps = db.query(LicitacionSnapshot).count()
        total_reglas = db.query(ReglaUsuario).filter_by(user_id=_u()).count()
        total_alertas = db.query(AlertaGenerada).filter_by(user_id=_u()).count()
    next_run = None
    if _scheduler and _scheduler.running:
        job = _scheduler.get_job("ciclo_diario")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()
    return jsonify({
        "status": "ok", "user": current_user.email, "plan": current_user.plan,
        "total_snapshots": total_snaps, "total_reglas": total_reglas,
        "total_alertas": total_alertas, "scheduler_next_run": next_run,
    })


@bp.route("/api/quota")
@login_required
def api_quota():
    """Uso de cuota de API del usuario actual."""
    from app.models import ApiQuotaLog
    from sqlalchemy import func
    fecha = _dt.utcnow().strftime("%Y-%m-%d")
    with get_db() as db:
        q = db.query(ApiQuotaLog).filter_by(user_id=_u(), fecha=fecha).first()
        usados   = q.requests if q else 0
        limite   = q.limite if q else 10_000
    return jsonify({
        "fecha": fecha,
        "requests_hoy": usados,
        "limite_diario": limite,
        "disponibles": max(0, limite - usados),
        "pct_usado": round(usados / limite * 100, 1) if limite else 0,
    })


@bp.route("/api/organismo/<nombre>")
@login_required
def api_organismo_perfil(nombre: str):
    """Perfil de un organismo comprador: frecuencia, monto promedio, categorías, estacionalidad."""
    from sqlalchemy import cast, String, func, extract
    with get_db() as db:
        base = db.query(LicitacionSnapshot).filter(
            cast(LicitacionSnapshot.datos["organismo"], String).ilike(f"%{nombre[:40]}%"))

        total = base.count()
        montos = base.filter(LicitacionSnapshot.monto_clp.isnot(None))
        monto_prom = montos.with_entities(func.avg(LicitacionSnapshot.monto_clp)).scalar() or 0
        monto_max  = montos.with_entities(func.max(LicitacionSnapshot.monto_clp)).scalar() or 0

        # Estacionalidad por mes
        estac = (db.query(
                    func.strftime("%m", LicitacionSnapshot.fecha_publicacion).label("mes"),
                    func.count(LicitacionSnapshot.id).label("n"),
                 ).filter(
                    cast(LicitacionSnapshot.datos["organismo"], String).ilike(f"%{nombre[:40]}%"),
                    LicitacionSnapshot.fecha_publicacion.isnot(None),
                 ).group_by("mes").order_by("mes").all())

        MESES = ["","Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
        estac_data = [{"mes": MESES[int(r[0])] if r[0] and int(r[0]) <= 12 else r[0], "n": r[1]}
                      for r in estac if r[0]]

    return jsonify({
        "organismo": nombre,
        "total_licitaciones": total,
        "monto_promedio_clp": int(monto_prom),
        "monto_maximo_clp":   int(monto_max),
        "estacionalidad": estac_data,
    })
