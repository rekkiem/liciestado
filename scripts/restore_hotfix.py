#!/usr/bin/env python3
"""One-shot: apply flash/es_pro/admin hotfix on top of current tree."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 1. flash import
routes = ROOT / "app/dashboard/routes.py"
t = routes.read_text(encoding="utf-8")
if "flash" not in t.split("from flask import")[1].split(")")[0]:
    t = t.replace(
        "Blueprint, abort, jsonify, redirect, render_template,",
        "Blueprint, abort, flash, jsonify, redirect, render_template,",
    )
    routes.write_text(t, encoding="utf-8")
    print("OK: flash import")
else:
    print("skip: flash already imported")

# 2. is_admin on User
models = ROOT / "app/models.py"
t = models.read_text(encoding="utf-8")
if "is_admin" not in t:
    t = t.replace(
        'activo:         Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)',
        'activo:         Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)\n'
        '    is_admin:       Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)',
    )
    print("OK: is_admin column")
old = '''    @property
    def es_pro(self) -> bool:
        return self.plan in ("pro", "enterprise")
'''
new = '''    @property
    def es_pro(self) -> bool:
        """Pro permanente o trial activo (trial_pro_hasta en UserConfig)."""
        if self.plan in ("pro", "enterprise"):
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
'''
if old in t:
    t = t.replace(old, new)
    print("OK: es_pro trial")
models.write_text(t, encoding="utf-8")

# 3. database migration hook
db = ROOT / "app/database.py"
t = db.read_text(encoding="utf-8")
if "_migrate_add_is_admin" not in t:
    t = t.replace(
        "    _migrate_add_user_id()\n    logger.info",
        "    _migrate_add_user_id()\n    _migrate_add_is_admin()\n    logger.info",
    )
    t = t.rstrip() + '''


def _migrate_add_is_admin():
    """Añade columna is_admin a users si no existe (SQLite-safe)."""
    with engine.connect() as conn:
        try:
            result = conn.execute(
                __import__("sqlalchemy").text("PRAGMA table_info(users)")
            )
            cols = [row[1] for row in result.fetchall()]
            if "is_admin" not in cols:
                conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"
                    )
                )
                conn.commit()
                logger.info("Migración: columna users.is_admin añadida")
        except Exception as e:
            logger.warning("Migración is_admin: %s", e)
'''
    db.write_text(t + "\n", encoding="utf-8")
    print("OK: database migration")
else:
    print("skip: database migration")

# 4. main create_admin
main = ROOT / "main.py"
t = main.read_text(encoding="utf-8")
if '"is_admin": True' not in t:
    t = t.replace(
        '{"plan": "pro"}',
        '{"plan": "pro", "is_admin": True}',
    )
    t = t.replace(
        'Admin creado: %s (plan=pro)',
        'Admin creado: %s (plan=pro, is_admin=True)',
    )
    main.write_text(t, encoding="utf-8")
    print("OK: main create_admin")
else:
    print("skip: main")

print("DONE — rebuild docker: docker compose up -d --build")
