"""
main.py — Entry point LiciEstado multi-tenant.
"""
from __future__ import annotations
import argparse
import logging
import os
import sys
import threading
from config import settings
from app.database import init_db, get_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")
_shutdown = threading.Event()


def run_once():
    from app.scheduler import ejecutar_ciclo_completo
    logger.info("Ejecutando ciclo --once…")
    ejecutar_ciclo_completo()
    logger.info("Ciclo --once finalizado.")
    sys.exit(0)


def create_admin(email: str, password: str):
    from app.auth import registrar_usuario, EmailYaRegistrado
    from app.models import User
    try:
        user = registrar_usuario(email, password, "Admin")
        with get_db() as db:
            db.query(User).filter_by(id=user.id).update({"plan": "pro", "is_admin": True})
        logger.info("Admin creado: %s (plan=pro, is_admin=True)", email)
    except EmailYaRegistrado:
        logger.info("Usuario ya existe: %s", email)
    sys.exit(0)


def run_server():
    logger.info("=== LiciEstado v1.0 iniciando ===")
    logger.info("BD: %s", settings.DATABASE_URL)
    logger.info("Scheduler: %02d:%02d (%s)", settings.SCHEDULER_HOUR, settings.SCHEDULER_MINUTE, settings.TIMEZONE)

    init_db()
    logger.info("BD inicializada.")

    from app.email_service import iniciar_worker
    iniciar_worker()
    logger.info("Worker de email iniciado.")

    from app.webhook_service import iniciar_worker_webhook
    iniciar_worker_webhook()
    logger.info("Worker de webhooks iniciado.")

    from app.scheduler import iniciar_scheduler
    iniciar_scheduler()
    logger.info("Scheduler iniciado.")

    from app.dashboard import create_app
    app = create_app()

    port = int(os.environ.get("PORT", 5000))
    def _run():
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    flask_thread = threading.Thread(target=_run, daemon=True)
    flask_thread.start()
    logger.info("Dashboard en http://localhost:%s", os.environ.get("PORT", 5000))
    logger.info("Landing:    http://localhost:%s/landing", os.environ.get("PORT", 5000))

    _shutdown.wait()
    logger.info("Deteniendo scheduler…")
    from app.scheduler import detener_scheduler
    detener_scheduler()
    logger.info("Apagado limpio.")


def main():
    p = argparse.ArgumentParser(description="LiciEstado multi-tenant")
    p.add_argument("--once",         action="store_true", help="Ciclo inmediato y salir")
    p.add_argument("--init-db",      action="store_true", help="Inicializar BD y salir")
    p.add_argument("--create-admin", nargs=2, metavar=("EMAIL","PASS"), help="Crear usuario admin Pro")
    args = p.parse_args()

    if args.init_db:
        init_db(); logger.info("BD inicializada."); sys.exit(0)
    if args.once:
        run_once()
    if args.create_admin:
        create_admin(*args.create_admin)
    run_server()


if __name__ == "__main__":
    main()
