"""VALORIX360 · Envío de correos (restablecimiento de contraseña) por SMTP.

Variables: SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM (por defecto SMTP_USER) y VALORIX_URL_APP.
Para desarrollo, VALORIX_CORREO_CONSOLA=1 imprime el enlace en el registro del servidor en vez de enviar un correo.
"""
import smtplib
import ssl
import sys
from email.message import EmailMessage
from urllib.parse import quote

from valorix_config import config_value

CUERPO = """Hola {nombre},

Recibimos una solicitud para restablecer la contraseña de tu cuenta de Valorix360.

Abre este enlace (vale {minutos} minutos y solo puede usarse una vez):
{enlace}

Si no fuiste tú, ignora este mensaje: tu contraseña no cambiará.

Valorix360
"""


def configurado():
    return bool(config_value("VALORIX_CORREO_CONSOLA") == "1" or (config_value("SMTP_HOST") and config_value("SMTP_USER")))


def enlace_restablecimiento(token):
    base = config_value("VALORIX_URL_APP", "http://localhost:8501").rstrip("/")
    return f"{base}/?restablecer={quote(token)}"


def enviar_restablecimiento(destino, nombre, token, minutos=30):
    """Devuelve True si el mensaje salió (o se imprimió en modo consola); False si falla o no hay SMTP configurado."""
    enlace = enlace_restablecimiento(token)
    if config_value("VALORIX_CORREO_CONSOLA") == "1":
        print(f"[correo-consola] Restablecer contraseña de {destino}: {enlace}", file=sys.stderr, flush=True)
        return True
    host, usuario = config_value("SMTP_HOST"), config_value("SMTP_USER")
    if not (host and usuario):
        return False
    msg = EmailMessage()
    msg["Subject"] = "Restablece tu contraseña de Valorix360"
    msg["From"] = config_value("SMTP_FROM") or usuario
    msg["To"] = destino
    msg.set_content(CUERPO.format(nombre=nombre, enlace=enlace, minutos=minutos))
    try:
        puerto = int(config_value("SMTP_PORT", "587"))
        contexto = ssl.create_default_context()
        if puerto == 465:
            with smtplib.SMTP_SSL(host, puerto, context=contexto, timeout=15) as s:
                s.login(usuario, config_value("SMTP_PASSWORD", ""))
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, puerto, timeout=15) as s:
                s.starttls(context=contexto)
                s.login(usuario, config_value("SMTP_PASSWORD", ""))
                s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError):
        return False
