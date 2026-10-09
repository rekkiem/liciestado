"""app/dashboard/routes.py — Rutas del dashboard multi-tenant."""
from __future__ import annotations

from flask import (
    Blueprint, abort, flash, jsonify, redirect, render_template,
    request, url_for, Response,
)
from flask_login import login_required, current_user
from sqlalchemy import cast, String, func

from app.database import get_db
from app.models import (
    ReglaUsuario, AlertaGenerada, LicitacionSnapshot, User,
)

bp = Blueprint("dashboard", __name__)


def _u() -> int:
    return int(current_user.id)


def _check_ticket():
    from app.auth import obtener_ticket_plano
    return obtener_ticket_plano(_u())


@bp.route("/dashboard")
@login_required
def home():
    with get_db() as db:
        reglas = (
            db.query(ReglaUsuario)
            .filter_by(user_id=_u())
            .order_by(ReglaUsuario.fecha_creacion.desc())
            .all()
        )
        alertas = (
            db.query(AlertaGenerada)
            .filter_by(user_id=_u())
            .order_by(AlertaGenerada.fecha_alerta.desc())
            .limit(20)
            .all()
        )
        n_reglas = len(reglas)
        n_activas = sum(1 for r in reglas if r.activa)
        n_alertas = db.query(AlertaGenerada).filter_by(user_id=_u()).count()
        from datetime import datetime, timedelta
        hoy = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        n_hoy = db.query(AlertaGenerada).filter(
            AlertaGenerada.user_id == _u(),
            AlertaGenerada.fecha_alerta >= hoy,
        ).count()
        rows = [{
            "id": r.id, "nombre": r.nombre_regla, "activa": r.activa,
            "tipo": r.tipo_entidad, "email": r.email_destino,
            "fecha_creacion": r.fecha_creacion,
            "fecha_ult_exec": r.fecha_ultima_ejecucion,
            "filtros": r.filtros or {},
        } for r in reglas]
        alertas_rows = [{
            "id": a.id,
            "entidad_id": a.entidad_id,
            "regla_nombre": a.regla.nombre_regla if a.regla else "—",
            "titulo": (a.datos_resumen or {}).get("titulo", a.entidad_id),
            "monto": (a.datos_resumen or {}).get("monto_clp"),
            "fecha_alerta": a.fecha_alerta,
        } for a in alertas]
    return render_template(
        "index.html",
        reglas=rows,
        alertas=alertas_rows,
        stats={
            "total_reglas": n_reglas,
            "reglas_activas": n_activas,
            "total_alertas": n_alertas,
            "alertas_hoy": n_hoy,
        },
    )


@bp.route("/reglas")
@login_required
def reglas_lista():
    """Listado de reglas — mismo contenido que el bloque del dashboard."""
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
    import json
    nombre   = request.form.get("nombre_regla", "").strip()
    tipo     = request.form.get("tipo_entidad", "licitacion").strip()
    email    = request.form.get("email_destino", current_user.email).strip()
    activa   = request.form.get("activa") == "on" or request.form.get("activa") == "true"
    filtros_raw = request.form.get("filtros", "{}").strip()
    try:
        filtros = json.loads(filtros_raw) if filtros_raw else {}
    except json.JSONDecodeError:
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
    ticket = _check_ticket()
    if not ticket:
        flash("Configura tu ticket de API primero.", "error")
        return redirect(url_for("auth.configuracion"))
    from app.scheduler import ejecutar_regla_manualmente
    try:
        stats = ejecutar_regla_manualmente(regla_id, ticket_override=ticket)
        if stats.get("error"):
            flash(stats["error"], "error")
        else:
            n = stats.get("alertas_nuevas", 0)
            flash(f"Regla ejecutada: {n} alertas nuevas (evaluadas {stats.get('entidades_evaluadas', 0)}).", "success")
    except Exception as e:
        flash(f"Error al ejecutar: {e}", "error")
    return redirect(url_for("dashboard.home"))


@bp.route("/alertas")
@login_required
def alertas():
    page = max(1, int(request.args.get("page", 1)))
    per = 30
    with get_db() as db:
        q = db.query(AlertaGenerada).filter_by(user_id=_u())
        total = q.count()
        items = q.order_by(AlertaGenerada.fecha_alerta.desc()).offset((page-1)*per).limit(per).all()
        reglas_sel = db.query(ReglaUsuario.id, ReglaUsuario.nombre_regla).filter_by(user_id=_u()).all()
        rows = [{
            "id": a.id,
            "entidad_id": a.entidad_id,
            "regla_nombre": a.regla.nombre_regla if a.regla else "—",
            "titulo": (a.datos_resumen or {}).get("titulo", a.entidad_id),
            "monto": (a.datos_resumen or {}).get("monto_clp"),
            "fecha_alerta": a.fecha_alerta,
            "enviado_email": a.enviado_email,
        } for a in items]
    return render_template(
        "alertas.html",
        alertas=rows,
        reglas=[{"id": r.id, "nombre": r.nombre_regla} for r in reglas_sel],
        page=page, per=per, total=total,
        regla_filtro=request.args.get("regla", ""),
    )


@bp.route("/alertas/<int:alerta_id>")
@login_required
def alerta_detalle(alerta_id: int):
    with get_db() as db:
        a = db.query(AlertaGenerada).filter_by(id=alerta_id, user_id=_u()).first()
        if not a:
            abort(404)
        data = {
            "id": a.id,
            "entidad_id": a.entidad_id,
            "regla_nombre": a.regla.nombre_regla if a.regla else "—",
            "datos": a.datos_resumen or {},
            "fecha_alerta": a.fecha_alerta,
            "enviado_email": a.enviado_email,
        }
    return render_template("alerta_detalle.html", alerta=data)


@bp.route("/licitaciones")
@login_required
def licitaciones_browser():
    from datetime import datetime as _dt
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "")
    region = request.args.get("region", "")
    mmin = request.args.get("mmin", "")
    mmax = request.args.get("mmax", "")
    page = max(1, int(request.args.get("page", 1)))
    pp = min(100, max(10, int(request.args.get("pp", 50))))
    orden = request.args.get("orden", "sinc_desc")

    with get_db() as db:
        base_q = db.query(LicitacionSnapshot)
        if q:
            base_q = base_q.filter(
                cast(LicitacionSnapshot.datos["titulo"], String).ilike(f"%{q}%")
                | LicitacionSnapshot.codigo.ilike(f"%{q}%")
            )
        if estado:
            base_q = base_q.filter(LicitacionSnapshot.estado.ilike(f"%{estado}%"))
        if region:
            try:
                base_q = base_q.filter(LicitacionSnapshot.region == int(region))
            except ValueError:
                pass
        if mmin:
            try:
                base_q = base_q.filter(LicitacionSnapshot.monto_clp >= int(mmin))
            except ValueError:
                pass
        if mmax:
            try:
                base_q = base_q.filter(LicitacionSnapshot.monto_clp <= int(mmax))
            except ValueError:
                pass

        orden_map = {
            "sinc_desc": LicitacionSnapshot.fecha_sincronizacion.desc(),
            "sinc_asc": LicitacionSnapshot.fecha_sincronizacion.asc(),
            "fecha_desc": LicitacionSnapshot.fecha_publicacion.desc().nulls_last(),
            "monto_desc": LicitacionSnapshot.monto_clp.desc().nulls_last(),
        }
        base_q = base_q.order_by(orden_map.get(orden, LicitacionSnapshot.fecha_sincronizacion.desc()))
        total = base_q.count()
        items = base_q.offset((page-1)*pp).limit(pp).all()
        rows = []
        for s in items:
            d = s.datos or {}
            rows.append({
                "id": s.id,
                "codigo": s.codigo,
                "titulo": d.get("titulo", s.codigo),
                "organismo": d.get("organismo") or d.get("nombre_organismo"),
                "monto": s.monto_clp,
                "estado": s.estado,
                "region": s.region,
                "nombre_region": d.get("nombre_region"),
                "fecha_pub": s.fecha_publicacion.strftime("%d-%m-%Y") if s.fecha_publicacion else None,
                "fecha_cierre": d.get("fecha_cierre"),
                "fecha_sinc": s.fecha_sincronizacion.strftime("%d-%m-%Y %H:%M") if s.fecha_sincronizacion else "",
            })
    return render_template(
        "licitaciones.html",
        items=rows, total=total, page=page, pp=pp,
        filters={"q": q, "estado": estado, "region": region, "mmin": mmin, "mmax": mmax, "orden": orden},
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
            "datos": d,
        }
    return render_template("licitacion_detalle.html", item=item)


@bp.route("/licitaciones/<int:snap_id>/analizar")
@login_required
def licitacion_analizar(snap_id: int):
    from app.bid_analyzer import bid_analyzer
    costo = request.args.get("costo")
    try:
        costo = int(costo) if costo else None
    except ValueError:
        costo = None
    analisis = bid_analyzer.analizar(snap_id, costo_propio=costo)
    if not analisis:
        abort(404)
    return render_template("licitacion_analisis.html", a=analisis)


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
