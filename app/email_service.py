"""app/email_service.py — Cola de emails con worker thread."""
from __future__ import annotations
import logging, queue, smtplib, threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Dict
from config import settings

logger = logging.getLogger(__name__)
_email_queue: queue.Queue = queue.Queue()
_worker_thread: threading.Thread | None = None

def _crear_smtp():
    if settings.SMTP_USE_TLS:
        smtp = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30)
        smtp.starttls()
    else:
        smtp = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30)
    if settings.SMTP_USER and settings.SMTP_PASSWORD:
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
    return smtp

def _enviar_raw(msg: MIMEMultipart, destinatarios: List[str], max_retries=3) -> bool:
    for attempt in range(max_retries):
        try:
            with _crear_smtp() as smtp:
                smtp.sendmail(settings.SMTP_FROM or settings.SMTP_USER, destinatarios, msg.as_string())
            return True
        except Exception as e:
            logger.warning("Error SMTP (intento %d/%d): %s", attempt+1, max_retries, e)
    return False

def _html_alerta(regla_nombre: str, entidad: Dict) -> str:
    monto_str = f"${entidad.get('monto_clp', 0):,.0f} CLP" if entidad.get("monto_clp") else "—"
    link = entidad.get("link_detalle", "#")
    return f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#f5f5f5;padding:20px">
  <div style="background:#07090f;border-radius:8px;padding:24px;color:#e6edf3">
    <h2 style="margin:0 0 4px;color:#e6a817">🏛 Nueva coincidencia: {regla_nombre}</h2>
    <p style="margin:0;color:#8b949e;font-size:12px">Sistema de alertas LiciEstado</p>
  </div>
  <div style="background:#fff;border-radius:8px;margin-top:12px;padding:20px">
    <h3 style="margin:0 0 12px;color:#1a1a2e">{entidad.get('titulo','Sin título')}</h3>
    <table style="width:100%;border-collapse:collapse">
      <tr><td style="padding:6px 0;color:#666;width:130px">Código</td><td style="padding:6px 0;font-weight:bold">{entidad.get('codigo','—')}</td></tr>
      <tr><td style="padding:6px 0;color:#666">Organismo</td><td style="padding:6px 0">{entidad.get('organismo','—')}</td></tr>
      <tr><td style="padding:6px 0;color:#666">Monto estimado</td><td style="padding:6px 0;color:#3fb950;font-weight:bold">{monto_str}</td></tr>
      <tr><td style="padding:6px 0;color:#666">Estado</td><td style="padding:6px 0">{entidad.get('estado','—')}</td></tr>
      <tr><td style="padding:6px 0;color:#666">Fecha cierre</td><td style="padding:6px 0">{entidad.get('fecha_cierre','—')}</td></tr>
    </table>
    <div style="margin-top:20px">
      <a href="{link}" style="background:#e6a817;color:#1c1917;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold">Ver en Mercado Público →</a>
    </div>
  </div>
</div>"""

def encolar_alerta(regla_nombre: str, entidad: Dict, destinatarios: List[str]) -> None:
    _email_queue.put({"tipo": "alerta", "regla_nombre": regla_nombre,
                      "entidad": entidad, "destinatarios": destinatarios})

def encolar_resumen_admin(stats: Dict) -> None:
    if not settings.ADMIN_EMAIL: return
    _email_queue.put({"tipo": "resumen_admin", "stats": stats,
                      "destinatarios": [settings.ADMIN_EMAIL]})

def _procesar_alerta(item: Dict):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[LiciEstado] Nueva coincidencia: {item['regla_nombre']}"
    msg["From"]    = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"]      = ", ".join(item["destinatarios"])
    msg.attach(MIMEText(_html_alerta(item["regla_nombre"], item["entidad"]), "html"))
    ok = _enviar_raw(msg, item["destinatarios"])
    if ok: logger.info("Email enviado: %s → %s", item["regla_nombre"], item["destinatarios"])
    else:  logger.error("Fallo envío email para regla: %s", item["regla_nombre"])

def _procesar_resumen_admin(item: Dict):
    stats = item["stats"]
    body = f"""<h2>Resumen Scheduler LiciEstado</h2>
<ul>
  <li>Usuarios procesados: {stats.get('usuarios_procesados',0)}</li>
  <li>Alertas nuevas: {stats.get('alertas_nuevas',0)}</li>
  <li>Errores: {stats.get('errores',0)}</li>
</ul>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "[LiciEstado Admin] Resumen ciclo diario"
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"]   = ", ".join(item["destinatarios"])
    msg.attach(MIMEText(body, "html"))
    _enviar_raw(msg, item["destinatarios"])

def _worker_loop():
    logger.info("Worker de correos arrancado (thread id=%d).", threading.get_ident())
    while True:
        try:
            item = _email_queue.get(timeout=5)
            if item is None: break
            if item.get("tipo") == "alerta": _procesar_alerta(item)
            elif item.get("tipo") == "digest": _procesar_digest(item)
            elif item.get("tipo") == "resumen_admin": _procesar_resumen_admin(item)
            _email_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logger.exception("Error en worker de correos: %s", e)

def iniciar_worker():
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive(): return
    logger.info("Worker de correos iniciado.")
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="email-worker")
    _worker_thread.start()

def detener_worker(timeout=10):
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        _email_queue.put(None)
        _worker_thread.join(timeout=timeout)


def _html_digest(alertas: list) -> str:
    filas = ""
    for a in alertas[:20]:
        d = a.get("datos", {})
        monto = f"${d.get('monto_clp',0):,.0f}" if d.get("monto_clp") else "—"
        link = d.get("link_detalle","#")
        filas += f"""
        <tr style="border-bottom:1px solid #21262d">
          <td style="padding:8px 10px;font-size:12px;color:#c9d1d9">{a.get('regla','—')}</td>
          <td style="padding:8px 10px;font-size:12px;color:#e6edf3">{d.get('titulo','—')[:60]}</td>
          <td style="padding:8px 10px;font-size:12px;color:#3fb950;font-family:monospace">{monto}</td>
          <td style="padding:8px 10px;font-size:12px"><a href="{link}" style="color:#e6a817">Ver →</a></td>
        </tr>"""
    n = len(alertas)
    return f"""
<div style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;background:#0d1117;padding:24px;border-radius:10px">
  <h2 style="color:#e6a817;margin:0 0 4px">🏛 LiciEstado — Resumen diario</h2>
  <p style="color:#8b949e;font-size:12px;margin:0 0 20px">{n} oportunidad(es) nueva(s) detectada(s)</p>
  <table style="width:100%;border-collapse:collapse;background:#161b22;border-radius:8px;overflow:hidden">
    <thead>
      <tr style="background:#21262d">
        <th style="padding:8px 10px;text-align:left;font-size:10px;color:#8b949e;text-transform:uppercase;letter-spacing:.5px">Regla</th>
        <th style="padding:8px 10px;text-align:left;font-size:10px;color:#8b949e;text-transform:uppercase">Título</th>
        <th style="padding:8px 10px;text-align:left;font-size:10px;color:#8b949e;text-transform:uppercase">Monto</th>
        <th style="padding:8px 10px;text-align:left;font-size:10px;color:#8b949e;text-transform:uppercase">Link</th>
      </tr>
    </thead>
    <tbody>{filas}</tbody>
  </table>
  {'<p style="color:#8b949e;font-size:11px;margin-top:12px">...y ' + str(n-20) + ' más. Ver todas en tu dashboard.</p>' if n > 20 else ''}
  <div style="margin-top:20px;text-align:center">
    <a href="http://localhost:5000/alertas" style="background:#e6a817;color:#1c1917;padding:10px 22px;border-radius:6px;text-decoration:none;font-weight:700;font-size:13px">
      Ver en LiciEstado →
    </a>
  </div>
</div>"""


def encolar_digest(email_destino: str, alertas: list) -> None:
    """Encola un resumen diario con múltiples alertas."""
    _email_queue.put({"tipo": "digest", "email_destino": email_destino, "alertas": alertas})


def _procesar_digest(item: dict):
    alertas = item.get("alertas", [])
    if not alertas:
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[LiciEstado] {len(alertas)} nueva(s) oportunidad(es) hoy"
    msg["From"]    = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"]      = item["email_destino"]
    msg.attach(MIMEText(_html_digest(alertas), "html"))
    ok = _enviar_raw(msg, [item["email_destino"]])
    if ok:
        logger.info("Digest enviado a %s (%d alertas)", item["email_destino"], len(alertas))
