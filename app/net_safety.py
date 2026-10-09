"""Validación de URLs de webhook anti-SSRF."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def validar_webhook_url(url: str) -> tuple[bool, str]:
    """
    Valida que una URL de webhook sea segura para solicitar desde el servidor.
    Returns: (ok, mensaje_error)
    """
    if not url or not isinstance(url, str):
        return False, "URL vacía"
    url = url.strip()
    if len(url) > 500:
        return False, "URL demasiado larga (máx. 500)"

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL inválida"

    if parsed.scheme != "https":
        return False, "Solo se permite HTTPS"
    if parsed.username or parsed.password:
        return False, "Credenciales en URL no permitidas"
    if not parsed.hostname:
        return False, "Host ausente"

    host = parsed.hostname
    if host.lower() in ("localhost",):
        return False, "Host no permitido"

    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False, "No se pudo resolver el host"
    except Exception as e:
        return False, f"Error resolviendo host: {e}"

    if not infos:
        return False, "Sin direcciones resueltas"

    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"IP inválida: {ip_str}"
        if getattr(ip, "ipv4_mapped", None) is not None:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            return False, f"IP no global no permitida: {ip}"
    return True, ""
