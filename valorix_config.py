import os
from urllib.parse import urlparse

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


class ErrorConfiguracion(ValueError):
    """Configuración insegura o incompleta para el entorno seleccionado."""


def _streamlit_secrets():
    try:
        return dict(st.secrets)
    except StreamlitSecretNotFoundError:
        return {}


def config_value(name, default=None):
    if name in os.environ:
        return os.environ[name]
    return _streamlit_secrets().get(name, default)


def validar_configuracion_produccion():
    """Rechaza configuraciones inseguras cuando la aplicación se marca como producción."""
    entorno = (config_value("VALORIX_ENTORNO", "local") or "").strip().lower()
    if entorno not in {"local", "produccion"}:
        raise ErrorConfiguracion("VALORIX_ENTORNO debe ser 'local' o 'produccion'.")
    if entorno != "produccion":
        return

    problemas = []
    cuentas = config_value("VALORIX_CUENTAS", "1") != "0"
    base = config_value("VALORIX_URL_APP", "")
    parsed = urlparse(base)
    if cuentas and not config_value("DATABASE_URL"):
        problemas.append("DATABASE_URL es obligatorio cuando las cuentas están activas")
    if parsed.scheme != "https" or not parsed.netloc:
        problemas.append("VALORIX_URL_APP debe ser una URL HTTPS pública")
    if cuentas and config_value("VALORIX_CORREO_CONSOLA") == "1":
        problemas.append("VALORIX_CORREO_CONSOLA debe estar desactivado")
    if cuentas and (not config_value("SMTP_HOST") or not config_value("SMTP_USER") or not config_value("SMTP_PASSWORD")):
        problemas.append("SMTP_HOST, SMTP_USER y SMTP_PASSWORD son obligatorios para recuperar contraseñas")
    if problemas:
        raise ErrorConfiguracion("Configuración de producción inválida: " + "; ".join(problemas) + ".")