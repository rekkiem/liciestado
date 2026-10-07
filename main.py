#!/usr/bin/env python3
"""
main.py — Punto de entrada LiciEstado multi-tenant.

  python main.py              # servidor + scheduler
  python main.py --once       # ciclo inmediato de todos los usuarios
  python main.py --init-db    # solo inicializar BD
  python main.py --create-admin email pass  # crear usuario admin
"""
import argparse, logging, os, re, signal, sys, threading

LOG_FMT  = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE = "%Y-%m-%d %H:%M:%S"
os.makedirs("logs", exist_ok=True)
logging.basicConfig(level=logging.INFO, format=LOG_FMT, datefmt=LOG_DATE,
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler("logs/app.log", encoding="utf-8")])

# Filtrar ANSI del FileHandler sin tocar WERKZEUG_RUN_MAIN
_wz_logger = logging.getLogger("werkzeug")
_wz_logger.propagate = True

class _StripAnsi(logging.Filter):
    _pat = re.compile(r"\x1b\[[0-9;]*m")
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = self._pat.sub("", record.msg)
        return True

for _h in logging.root.handlers:
    if isinstance(_h, logging.FileHandler):
        _h.addFilter(_StripAnsi())

logger = logging.getLogger("main")

from config import settings
from app.database import init_db

_shutdown = threading.Event()
signal.signal(signal.SIGINT,  lambda s,f: _shutdown.set())
signal.signal(signal.SIGTERM, lambda s,f: _shutdown.set())


def run_once():
    logger.info("Modo --once: ejecutando ciclo completo…")
    init_db()
    from app.scheduler import ejecutar_ciclo_completo
    stats = ejecutar_ciclo_completo()
    alertas_n = stats.get("alertas_nuevas", stats.get("alertas_generadas", 0))
    logger.info("Ciclo completado: %d usuarios, %d alertas nuevas.",
                stats.get("usuarios_procesados", 0), alertas_n)
    sys.exit(0)


def create_admin(email: str, password: str):
    init_db()
    from app.auth import registrar_usuario, EmailYaRegistrado
    from app.database import get_db
    from app.models import User
    try:
        user = registrar_usuario(email, password, "Admin")
        with get_db() as db:
            db.query(User).filter_by(id=user.id).update({"plan": "pro"})
        logger.info("Admin creado: %s (plan=pro)", email)
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


try:
    from app.security import check_insecure_defaults
    check_insecure_defaults()
except Exception:
    pass

if __name__ == "__main__":
    main()
