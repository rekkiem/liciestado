#!/usr/bin/env python3
"""One-shot hotfix: flash, es_pro trial, is_admin, admin panel. Safe to re-run."""
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
GOOD = "https://raw.githubusercontent.com/rekkiem/liciestado/eed645e33685b03bf9d83276b1be11c8e70b8a60"

def ensure_file(rel: str, min_size: int = 100):
    path = ROOT / rel
    if path.exists() and path.stat().st_size >= min_size:
        return
    url = f"{GOOD}/{rel}"
    print(f"Restoring {rel} from good commit ...")
    data = urllib.request.urlopen(url, timeout=30).read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"  wrote {len(data)} bytes")

ensure_file("app/dashboard/routes.py", 1000)
ensure_file("app/models.py", 1000)
ensure_file("main.py", 500)

routes = ROOT / "app/dashboard/routes.py"
t = routes.read_text(encoding="utf-8")
if "flash" not in t.split("from flask import")[1].split(")")[0]:
    t = t.replace(
        "Blueprint, abort, jsonify, redirect, render_template,",
        "Blueprint, abort, flash, jsonify, redirect, render_template,",
    )
    print("OK: flash import")
else:
    print("skip: flash")

if "/admin/users" not in t:
    t = t.rstrip() + """

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
"""
    print("OK: admin routes")
routes.write_text(t + "\n", encoding="utf-8")

models = ROOT / "app/models.py"
t = models.read_text(encoding="utf-8")
if "is_admin" not in t:
    t = t.replace(
        "activo:         Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)",
        "activo:         Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)\n"
        "    is_admin:       Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)",
    )
    print("OK: is_admin")
old = """    @property
    def es_pro(self) -> bool:
        return self.plan in (\"pro\", \"enterprise\")
"""
new = """    @property
    def es_pro(self) -> bool:
        \"\"\"Pro permanente o trial activo.\"\"\"
        if self.plan in (\"pro\", \"enterprise\"):
            return True
        try:
            from app.database import get_db
            from datetime import datetime
            with get_db() as db:
                cfg = db.query(UserConfig).filter_by(user_id=self.id).first()
                if cfg and cfg.trial_pro_hasta and cfg.trial_pro_hasta > datetime.utcnow():
                    return True
        except Exception:
            pass
        return False
"""
if old in t:
    t = t.replace(old, new)
    print("OK: es_pro trial")
models.write_text(t, encoding="utf-8")

db = ROOT / "app/database.py"
t = db.read_text(encoding="utf-8")
if "_migrate_add_is_admin" not in t:
    t = t.replace(
        "    _migrate_add_user_id()\n    logger.info",
        "    _migrate_add_user_id()\n    _migrate_add_is_admin()\n    logger.info",
    )
    t = t.rstrip() + """


def _migrate_add_is_admin():
    with engine.connect() as conn:
        try:
            result = conn.execute(__import__("sqlalchemy").text("PRAGMA table_info(users)"))
            cols = [row[1] for row in result.fetchall()]
            if "is_admin" not in cols:
                conn.execute(__import__("sqlalchemy").text(
                    "ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
                conn.commit()
                logger.info("Migracion: users.is_admin anadida")
        except Exception as e:
            logger.warning("Migracion is_admin: %s", e)
"""
    db.write_text(t + "\n", encoding="utf-8")
    print("OK: database migration")

main = ROOT / "main.py"
t = main.read_text(encoding="utf-8")
if '"is_admin": True' not in t:
    t = t.replace('{"plan": "pro"}', '{"plan": "pro", "is_admin": True}')
    t = t.replace("Admin creado: %s (plan=pro)", "Admin creado: %s (plan=pro, is_admin=True)")
    main.write_text(t, encoding="utf-8")
    print("OK: main create_admin")

tpl = ROOT / "app/dashboard/templates/admin_users.html"
if not tpl.exists() or tpl.stat().st_size < 50:
    tpl.write_text("""{% extends "base.html" %}
{% block title %}Admin · Usuarios{% endblock %}
{% block content %}
<div class="page-header"><h1>Usuarios registrados</h1></div>
<div class="card" style="overflow-x:auto">
<table class="table" style="width:100%;font-size:13px">
<thead><tr>
<th>ID</th><th>Email</th><th>Plan</th><th>Pro</th><th>Activo</th><th>Admin</th><th></th>
</tr></thead>
<tbody>
{% for u in users %}
<tr>
<td>{{ u.id }}</td><td>{{ u.email }}</td><td>{{ u.plan }}</td>
<td>{% if u.es_pro %}OK{% endif %}</td>
<td>{% if u.activo %}Si{% else %}No{% endif %}</td>
<td>{% if u.is_admin %}ADMIN{% endif %}</td>
<td>{% if u.id != current_user.id %}
<form method="post" action="{{ url_for('dashboard.admin_user_toggle', user_id=u.id) }}">
<button type="submit" class="btn btn-ghost">{% if u.activo %}Desactivar{% else %}Activar{% endif %}</button>
</form>{% endif %}</td>
</tr>
{% endfor %}
</tbody></table></div>
{% endblock %}
""", encoding="utf-8")
    print("OK: admin_users.html")

print("DONE. Rebuild: docker compose up -d --build")
