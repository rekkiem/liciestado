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
    Blueprint, abort, flash, jsonify, redirect, render_template,
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


def _u() -> int:
    return int(current_user.id)


def _check_ticket():
    from app.auth import obtener_ticket_plano
    return bool(obtener_ticket_plano(_u()))


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


@bp.route("/reglas")
@login_required
def reglas_lista():
    """Alias del dashboard para el menú lateral."""
    return home()


@bp.route("/reglas/nueva", methods=["GET", "POST"])
@login_required
def regla_nueva():
    if request.method == "POST":
        return _guardar_regla(None)
    return render_template("regla_form.html", form_data={}, regla=None)


@bp.route("/reglas/<int:regla_id>/editar", methods=["GET", "POST"])
@login_required
def regla_editar(regla_id: int):
    if request.method == "POST":
        return _guardar_regla(regla_id)
    with get_db() as db:
        regla = db.query(ReglaUsuario).filter_by(id=regla_id, user_id=_u()).first()
        if not regla:
            abort(404)
        form_data = {
            "id": regla.id, "nombre": regla.nombre_regla, "activa": regla.activa,
            "tipo": regla.tipo_entidad, "email": regla.email_destino,
            "filtros": regla.filtros or {},
        }
    return render_template("regla_form.html", form_data=form_data, regla=regla)


def _guardar_regla(regla_id):
    nombre   = request.form.get("nombre_regla", "").strip()
    tipo     = request.form.get("tipo_entidad", "licitacion").strip()
    email    = request.form.get("email_destino", current_user.email).strip()
    activa   = request.form.get("activa") in ("on", "true", "1", True)
    filtros_raw = request.form.get("filtros", "{}").strip()
    try:
        filtros = _json.loads(filtros_raw) if filtros_raw else {}
    except Exception:
        flash("JSON de filtros inválido.", "error")
        return redirect(request.url)
    if not nombre:
        flash("El nombre es obligatorio.", "error")
        return redirect(request.url)
    with get_db() as db:
        if regla_id:
            r = db.query(ReglaUsuario).filter_by(id=regla_id, user_id=_u()).first()
            if not r:
                abort(404)
            r.nombre_regla = nombre
            r.tipo_entidad = tipo
            r.email_destino = email
            r.filtros = filtros
            r.activa = activa
            flash("Regla actualizada.", "success")
        else:
            n = db.query(ReglaUsuario).filter_by(user_id=_u()).count()
            if n >= current_user.limite_reglas:
                flash("Límite de reglas alcanzado. Mejora a Pro.", "error")
                return redirect(url_for("dashboard.home"))
            db.add(ReglaUsuario(
                user_id=_u(), nombre_regla=nombre, tipo_entidad=tipo,
                email_destino=email, filtros=filtros, activa=activa,
            ))
            flash("Regla creada.", "success")
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
    from app.auth import obtener_ticket_plano
    ticket = obtener_ticket_plano(_u())
    if not ticket:
        flash("Configura tu ticket de API primero.", "error")
        return redirect(url_for("auth.configuracion"))
    try:
        stats = ejecutar_regla_manualmente(regla_id, ticket_override=ticket)
        if stats.get("error"):
            flash(stats["error"], "error")
        else:
            n = stats.get("alertas_nuevas", 0)
            flash(
                f"Regla ejecutada: {n} alertas nuevas "
                f"(evaluadas {stats.get('entidades_evaluadas', 0)}).",
                "success",
            )
    except Exception as e:
        logger.exception("Error ejecutando regla %s", regla_id)
        flash(f"Error al ejecutar: {e}", "error")
    return redirect(url_for("dashboard.home"))


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
                "codigo": a.entidad_id,
                "titulo": d.get("titulo", a.entidad_id),
                "organismo": d.get("organismo"),
                "region": d.get("region"),
                "monto_clp": d.get("monto_clp"),
                "fecha_alerta": a.fecha_alerta,
                "enviado_email": a.enviado_email,
                "tipo": d.get("tipo", "licitacion"),
            })

        reglas_select_data = [{"id": r[0], "nombre": r[1]} for r in reglas_sel]

    return render_template(
        "alertas.html",
        alertas=alertas_data,
        total=total,
        total_paginas=max(1, (total + per_page - 1) // per_page),
        page=page,
        per_page=per_page,
        tipo_filtro=tipo_filtro,
        regla_filtro=regla_filtro,
        reglas_select=reglas_select_data,
    )


@bp.route("/alertas/<int:alerta_id>")
@login_required
def alerta_detalle(alerta_id: int):
    with get_db() as db:
        a = db.query(AlertaGenerada).filter_by(id=alerta_id, user_id=_u()).first()
        if not a:
            abort(404)
        d = a.datos_resumen or {}
        data = {
            "id": a.id,
            "entidad_id": a.entidad_id,
            "regla_nombre": a.regla.nombre_regla if a.regla else "—",
            "datos": d,
            "fecha_alerta": a.fecha_alerta,
            "enviado_email": a.enviado_email,
            "titulo": d.get("titulo", a.entidad_id),
            "tipo": d.get("tipo", "licitacion"),
        }
    return render_template("alerta_detalle.html", alerta=data)


@bp.route("/licitaciones")
@login_required
def licitaciones_browser():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("pp", 50, type=int), 200)
    q = request.args.get("q", "").strip()
    f_tipo = request.args.get("tipo", "").strip()
    f_estado = request.args.get("estado", "").strip()
    f_region = request.args.get("region", "").strip()
    f_mmin = request.args.get("mmin", "").strip()
    f_mmax = request.args.get("mmax", "").strip()
    f_fd = request.args.get("fd", "").strip()
    f_fh = request.args.get("fh", "").strip()
    f_enr = request.args.get("enr", "").strip()
    f_org = request.args.get("org", "").strip()
    orden = request.args.get("orden", "sinc_desc")

    with get_db() as db:
        base_q = db.query(LicitacionSnapshot)
        if f_tipo:
            base_q = base_q.filter(LicitacionSnapshot.tipo == f_tipo)
        if f_estado:
            base_q = base_q.filter(LicitacionSnapshot.estado == f_estado)
        if f_region:
            try:
                base_q = base_q.filter(LicitacionSnapshot.region == int(f_region))
            except ValueError:
                pass
        if q:
            like = f"%{q}%"
            base_q = base_q.filter(
                LicitacionSnapshot.codigo.ilike(like)
                | cast(LicitacionSnapshot.datos["titulo"], String).ilike(like)
            )
        if f_mmin:
            try:
                base_q = base_q.filter(LicitacionSnapshot.monto_clp >= int(f_mmin))
            except ValueError:
                pass
        if f_mmax:
            try:
                base_q = base_q.filter(LicitacionSnapshot.monto_clp <= int(f_mmax))
            except ValueError:
                pass
        if f_org:
            base_q = base_q.filter(
                cast(LicitacionSnapshot.datos["organismo"], String).ilike(f"%{f_org}%")
            )

        orden_map = {
            "sinc_desc": LicitacionSnapshot.fecha_sincronizacion.desc(),
            "sinc_asc": LicitacionSnapshot.fecha_sincronizacion.asc(),
            "monto_desc": LicitacionSnapshot.monto_clp.desc().nulls_last(),
            "fecha_desc": LicitacionSnapshot.fecha_publicacion.desc().nulls_last(),
        }
        base_q = base_q.order_by(
            orden_map.get(orden, LicitacionSnapshot.fecha_sincronizacion.desc())
        )

        total = base_q.count()
        snaps = base_q.offset((page - 1) * per_page).limit(per_page).all()

        total_all = db.query(func.count(LicitacionSnapshot.id)).scalar() or 0
        con_datos = db.query(func.count(LicitacionSnapshot.id)).filter(
            LicitacionSnapshot.monto_clp.isnot(None)
        ).scalar() or 0
        monto_total = db.query(func.sum(LicitacionSnapshot.monto_clp)).scalar() or 0
        monto_prom = (monto_total / con_datos) if con_datos else 0

        estados_q = (
            db.query(LicitacionSnapshot.estado, func.count(LicitacionSnapshot.id))
            .filter(LicitacionSnapshot.estado.isnot(None), LicitacionSnapshot.estado != "")
            .group_by(LicitacionSnapshot.estado)
            .order_by(func.count(LicitacionSnapshot.id).desc())
            .all()
        )
        estados_opts = [(e, n) for e, n in estados_q if e]

        regiones_q = (
            db.query(LicitacionSnapshot.region, func.count(LicitacionSnapshot.id))
            .filter(LicitacionSnapshot.region.isnot(None))
            .group_by(LicitacionSnapshot.region)
            .order_by(func.count(LicitacionSnapshot.id).desc())
            .all()
        )
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

    qs_base = (
        f"q={q}&tipo={f_tipo}&estado={f_estado}&region={f_region}"
        f"&mmin={f_mmin}&mmax={f_mmax}&fd={f_fd}&fh={f_fh}&enr={f_enr}"
        f"&org={f_org}&pp={per_page}&orden={orden}"
    )
    n_filtros = sum(1 for v in [q, f_tipo, f_estado, f_region, f_mmin, f_mmax, f_fd, f_fh, f_enr, f_org] if v)
    return render_template(
        "licitaciones.html",
        rows=rows, page=page, per_page=per_page,
        total=total, total_paginas=max(1, (total + per_page - 1) // per_page),
        q=q, f_tipo=f_tipo, f_estado=f_estado, f_region=f_region,
        f_mmin=f_mmin, f_mmax=f_mmax, f_fd=f_fd, f_fh=f_fh, f_enr=f_enr,
        orden=orden, f_org=f_org, estados_opts=estados_opts,
        regiones_opts=regiones_opts, REGIONES_CHILE=REGIONES_CHILE,
        total_all=total_all, con_datos=con_datos, sin_datos=total_all - con_datos,
        monto_total=monto_total, monto_prom=int(monto_prom), qs_base=qs_base,
        n_filtros=n_filtros, es_pro=current_user.es_pro,
    )


@bp.route("/licitaciones/<int:snap_id>")
@login_required
def licitacion_detalle(snap_id: int):
    with get_db() as db:
        s = db.query(LicitacionSnapshot).filter_by(id=snap_id).first()
        if not s:
            abort(404)
        d = s.datos or {}
        item = {
            "id": s.id, "codigo": s.codigo, "titulo": d.get("titulo", s.codigo),
            "organismo": d.get("organismo") or d.get("nombre_organismo"),
            "monto": s.monto_clp, "estado": s.estado, "region": s.region,
            "nombre_region": d.get("nombre_region"),
            "fecha_pub": s.fecha_publicacion, "fecha_cierre": d.get("fecha_cierre"),
            "datos": d, "tipo": s.tipo,
            "link": d.get("link_detalle") or "",
        }
    return render_template("licitacion_detalle.html", item=item)


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
    except Exception as e:
        logger.exception("Error en bid analyzer snap_id=%s", snap_id)
        flash(f"No se pudo analizar: {e}", "error")
        return redirect(url_for("dashboard.licitacion_detalle", snap_id=snap_id))
    if not analisis:
        abort(404)
    curva_json = _json.dumps(getattr(analisis.bid_optimo, "curva_precios", []) or [])
    return render_template(
        "licitacion_analisis.html",
        a=analisis,
        curva_json=curva_json,
        costo_input=costo or "",
        snap_id=snap_id,
    )


@bp.route("/analytics")
@login_required
def analytics_dashboard():
    return render_template("analytics.html")


def _require_admin():
    if not getattr(current_user, "is_admin", False):
        abort(403)


@bp.route("/admin/users")
@login_required
def admin_users():
    _require_admin()
    with get_db() as db:
        from app.models import User, UserConfig
        users = db.query(User).order_by(User.fecha_registro.desc()).limit(200).all()
        rows = []
        for u in users:
            cfg = db.query(UserConfig).filter_by(user_id=u.id).first()
            rows.append({
                "id": u.id, "email": u.email, "nombre": u.nombre, "plan": u.plan,
                "activo": u.activo, "is_admin": getattr(u, "is_admin", False),
                "es_pro": u.es_pro, "fecha_registro": u.fecha_registro,
                "trial_pro_hasta": cfg.trial_pro_hasta if cfg else None,
                "n_reglas": u.reglas.count() if u.reglas else 0,
            })
    return render_template("admin_users.html", users=rows)


@bp.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@login_required
def admin_user_toggle(user_id: int):
    _require_admin()
    if user_id == current_user.id:
        flash("No puedes desactivarte a ti mismo.", "error")
        return redirect(url_for("dashboard.admin_users"))
    with get_db() as db:
        from app.models import User
        u = db.query(User).filter_by(id=user_id).first()
        if not u:
            abort(404)
        u.activo = not u.activo
        estado = "activado" if u.activo else "desactivado"
    flash(f"Usuario {estado}.", "success")
    return redirect(url_for("dashboard.admin_users"))
