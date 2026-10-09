from flask import Flask, redirect, url_for
from flask_login import LoginManager

from config import settings

login_manager = LoginManager()

def _format_number(value):
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return value or "—"

def create_app() -> Flask:
    from app.security import check_insecure_defaults
    check_insecure_defaults()

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    app.config["WTF_CSRF_ENABLED"] = not app.config.get("TESTING", False)
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600

    # CSRF
    from app.security import csrf, add_security_headers
    csrf.init_app(app)
    app.after_request(add_security_headers)

    # Flask-Login
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Inicia sesión para continuar."
    login_manager.login_message_category = "info"

    from app.auth import cargar_usuario
    login_manager.user_loader(cargar_usuario)

    from app.dashboard.routes import bp as dashboard_bp
    from app.dashboard.auth_routes import bp as auth_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)

    app.jinja_env.filters["format_number"] = _format_number
    app.jinja_env.filters["fmt_monto"] = lambda v: f"${int(v):,.0f}" if v else "—"

    @app.route("/")
    def index():
        from flask_login import current_user
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.home"))
        return redirect(url_for("auth.landing"))

    return app
