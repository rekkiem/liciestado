"""
app/dashboard/auth_routes.py — Rutas de autenticación.

  GET  /landing          → página pública de marketing
  GET  /login            → formulario de login
  POST /login
  GET  /register         → formulario de registro
  POST /register
  GET  /logout
  GET  /configuracion    → perfil + ticket + plan
  POST /configuracion/ticket
  POST /configuracion/password
"""
import logging
from datetime import datetime, timezone, timedelta
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, abort,
)
from flask_login import login_user, logout_user, login_required, current_user

from app.auth import (
    registrar_usuario, autenticar_usuario,
    guardar_ticket, validar_ticket_api,
    obtener_ticket_plano, cambiar_password,
    EmailYaRegistrado, PasswordDebil,
)
from app.database import get_db
from app.models import User, UserTicket

logger = logging.getLogger(__name__)
bp = Blueprint("auth", __name__)


@bp.route("/landing")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))
    return render_template("auth/landing.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    if request.method == "POST":
        from app.security import check_auth_rate_limit
        check_auth_rate_limit()
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = autenticar_usuario(email, password)
        if user:
            login_user(user, remember=remember)
            next_url = request.args.get("next") or url_for("dashboard.home")
            flash(f"Bienvenido, {user.nombre or user.email.split('@')[0]} 👋", "success")
            return redirect(next_url)
        else:
            flash("Email o contraseña incorrectos.", "error")

    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.home"))

    if request.method == "POST":
        email     = request.form.get("email", "").strip()
        password  = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        nombre    = request.form.get("nombre", "").strip()

        if password != password2:
            flash("Las contraseñas no coinciden.", "error")
            return render_template("auth/register.html", email=email, nombre=nombre)

        try:
            user = registrar_usuario(email, password, nombre)
            login_user(user, remember=True)
            from app.models import UserConfig
            trial_hasta = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=14)
            with get_db() as db:
                db.add(UserConfig(user_id=user.id, notif_mode="digest",
                                  trial_pro_hasta=trial_hasta))
                db.query(User).filter_by(id=user.id).update({"plan": "free"})
            flash("¡Cuenta creada! 🎉 Tienes 14 días de Plan Pro de prueba. Ahora configura tu ticket de Mercado Público.", "success")
            return redirect(url_for("auth.onboarding"))
        except EmailYaRegistrado:
            flash("Ese email ya está registrado. ¿Quieres iniciar sesión?", "error")
        except PasswordDebil as e:
            flash(str(e), "error")

    return render_template("auth/register.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for("auth.landing"))


@bp.route("/configuracion")
@login_required
def configuracion():
    ticket_preview = None
    tiene_ticket   = False

    ticket_raw = obtener_ticket_plano(current_user.id)
    if ticket_raw:
        tiene_ticket   = True
        ticket_preview = ticket_raw[:8] + "…" + ticket_raw[-4:]

    with get_db() as db:
        user = db.query(User).filter_by(id=current_user.id).first()
        stats = {
            "total_reglas":  user.reglas.count() if user else 0,
            "total_alertas": user.alertas.count() if user else 0,
        }

    from app.models import UserConfig
    with get_db() as db2:
        cfg = db2.query(UserConfig).filter_by(user_id=current_user.id).first()
        cfg_data = {"notif_mode": cfg.notif_mode if cfg else "digest",
                    "webhook_url": cfg.webhook_url if cfg else None,
                    "webhook_activo": cfg.webhook_activo if cfg else False,
                    "trial_pro_hasta": cfg.trial_pro_hasta if cfg else None} if cfg else None
    return render_template(
        "auth/configuracion.html",
        tiene_ticket   = tiene_ticket,
        ticket_preview = ticket_preview,
        stats          = stats,
        PLANES = _PLANES,
        cfg    = cfg_data,
    )


@bp.route("/configuracion/ticket", methods=["POST"])
@login_required
def configuracion_ticket():
    ticket = request.form.get("ticket", "").strip()
    if not ticket:
        flash("El ticket no puede estar vacío.", "error")
        return redirect(url_for("auth.configuracion"))

    valido, mensaje = validar_ticket_api(ticket)
    if not valido:
        flash(f"Ticket inválido: {mensaje}", "error")
        return redirect(url_for("auth.configuracion"))

    guardar_ticket(current_user.id, ticket)
    flash("✅ Ticket guardado y validado correctamente.", "success")
    return redirect(url_for("auth.configuracion"))


@bp.route("/configuracion/password", methods=["POST"])
@login_required
def configuracion_password():
    actual = request.form.get("password_actual", "")
    nuevo  = request.form.get("password_nuevo", "")
    nuevo2 = request.form.get("password_nuevo2", "")

    if nuevo != nuevo2:
        flash("Las contraseñas nuevas no coinciden.", "error")
        return redirect(url_for("auth.configuracion"))

    ok, msg = cambiar_password(current_user.id, actual, nuevo)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("auth.configuracion"))


@bp.route("/upgrade")
@login_required
def upgrade():
    return render_template("auth/upgrade.html", PLANES=_PLANES)


@bp.route("/upgrade/<plan>", methods=["POST"])
@login_required
def upgrade_plan(plan: str):
    if plan not in ("pro", "free"):
        abort(400)
    if plan == "pro":
        flash(
            "El upgrade a Pro permanente aún no está habilitado (falta integración de pagos). "
            "Si tienes trial activo, sigue disfrutando del Plan Pro hasta que expire.",
            "warning",
        )
        return redirect(url_for("auth.configuracion"))
    with get_db() as db:
        db.query(User).filter_by(id=current_user.id).update({"plan": "free"})
    flash("Plan cambiado a Free.", "success")
    return redirect(url_for("auth.configuracion"))


_PLANES = {
    "free": {
        "nombre":  "Free",
        "precio":  0,
        "moneda":  "USD",
        "features": [
            "3 reglas de alerta",
            "Alertas diarias por email",
            "Acceso a licitaciones descargadas",
            "Dashboard básico",
        ],
        "limitaciones": ["Sin bid analyzer", "Sin analítica avanzada"],
    },
    "pro": {
        "nombre":  "Pro",
        "precio":  49,
        "moneda":  "USD",
        "features": [
            "Reglas ilimitadas",
            "Bid Analyzer estadístico (Monte Carlo)",
            "Analítica avanzada por categoría/región",
            "Export CSV de alertas",
            "Soporte prioritario",
        ],
        "limitaciones": [],
    },
}


@bp.route("/onboarding")
@login_required
def onboarding():
    from app.auth import obtener_ticket_plano
    tiene_ticket = bool(obtener_ticket_plano(current_user.id))
    with get_db() as db:
        from app.models import ReglaUsuario
        n_reglas = db.query(ReglaUsuario).filter_by(user_id=current_user.id).count()
    return render_template("auth/onboarding.html",
        tiene_ticket=tiene_ticket, n_reglas=n_reglas)


@bp.route("/configuracion/webhook", methods=["POST"])
@login_required
def configuracion_webhook():
    from app.models import UserConfig
    from app.net_safety import validar_webhook_url
    url    = request.form.get("webhook_url", "").strip()
    activo = request.form.get("webhook_activo") == "1"
    modo   = request.form.get("notif_mode", "digest")

    if url:
        ok, msg = validar_webhook_url(url)
        if not ok:
            flash(f"URL de webhook no permitida: {msg}", "error")
            return redirect(url_for("auth.configuracion"))

    with get_db() as db:
        cfg = db.query(UserConfig).filter_by(user_id=current_user.id).first()
        if cfg:
            cfg.webhook_url = url or None
            cfg.webhook_activo = activo and bool(url)
            cfg.notif_mode = modo
        else:
            db.add(UserConfig(user_id=current_user.id, webhook_url=url or None,
                              webhook_activo=activo and bool(url), notif_mode=modo))
    flash("Configuración de notificaciones guardada.", "success")
    return redirect(url_for("auth.configuracion"))


@bp.route("/alertas/export.csv")
@login_required
def alertas_export_csv():
    import csv, io
    from app.models import AlertaGenerada
    with get_db() as db:
        alertas = db.query(AlertaGenerada).filter_by(
            user_id=current_user.id).order_by(
            AlertaGenerada.fecha_alerta.desc()).limit(5000).all()
        filas = []
        for a in alertas:
            d = a.datos_resumen or {}
            filas.append([a.entidad_id, d.get("titulo",""), d.get("organismo",""),
                          d.get("estado",""), d.get("monto_clp",""), d.get("region",""),
                          d.get("fecha_cierre",""), a.fecha_alerta.strftime("%Y-%m-%d %H:%M") if a.fecha_alerta else "",
                          a.enviado_email, d.get("link_detalle","")])

    buf = io.StringIO(); buf.write("\ufeff")
    w = csv.writer(buf)
    w.writerow(["Codigo","Titulo","Organismo","Estado","Monto_CLP","Region",
                "Fecha_Cierre","Fecha_Alerta","Email_Enviado","Link"])
    for f in filas: w.writerow(f)
    from flask import Response
    from datetime import datetime as _dt
    ts = _dt.now().strftime("%Y%m%d_%H%M")
    return Response(buf.getvalue(), mimetype="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename=alertas_liciestado_{ts}.csv"})
