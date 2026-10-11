"""Pruebas de recuperación de contraseña y envío de correo."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import valorix_correo  # noqa: E402
from valorix_db import MAX_SOLICITUDES_HORA, Almacen, ErrorCuenta  # noqa: E402

CLAVE = "una-clave-segura-123"
NUEVA = "otra-clave-mas-larga-456"


@pytest.fixture
def db(tmp_path):
    a = Almacen(tmp_path / "r.db")
    a.crear_usuario("ana@empresa.com", "Ana", CLAVE, True)
    return a


def test_restablecer_cambia_la_clave_y_el_token_sirve_una_vez(db):
    token, nombre = db.solicitar_restablecimiento("ANA@empresa.com")
    assert nombre == "Ana"
    db.restablecer(token, NUEVA)
    assert db.autenticar("ana@empresa.com", NUEVA) is not None
    assert db.autenticar("ana@empresa.com", CLAVE) is None
    with pytest.raises(ErrorCuenta):
        db.restablecer(token, "una-tercera-clave-789")


def test_el_token_no_se_guarda_en_claro(db):
    token, _ = db.solicitar_restablecimiento("ana@empresa.com")
    with db.engine.connect() as con:
        guardado = con.execute(text("SELECT token_hash FROM restablecimientos")).scalar()
    assert token not in guardado and len(guardado) == 64


def test_correo_inexistente_no_genera_token(db):
    assert db.solicitar_restablecimiento("nadie@empresa.com") is None


def test_token_invalido_o_vencido_se_rechaza(db):
    with pytest.raises(ErrorCuenta):
        db.restablecer("token-inventado", NUEVA)
    token, _ = db.solicitar_restablecimiento("ana@empresa.com")
    with db.engine.begin() as con:
        con.execute(text("UPDATE restablecimientos SET expira = :e"), {"e": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()})
    with pytest.raises(ErrorCuenta):
        db.restablecer(token, NUEVA)


def test_clave_nueva_debe_cumplir_el_minimo(db):
    token, _ = db.solicitar_restablecimiento("ana@empresa.com")
    with pytest.raises(ErrorCuenta):
        db.restablecer(token, "corta")
    db.restablecer(token, NUEVA)  # el intento fallido no gasta el token


def test_limite_de_solicitudes_por_hora(db):
    for _ in range(MAX_SOLICITUDES_HORA):
        assert db.solicitar_restablecimiento("ana@empresa.com") is not None
    assert db.solicitar_restablecimiento("ana@empresa.com") is None


def test_restablecer_desbloquea_la_cuenta(db):
    for _ in range(5):
        db.autenticar("ana@empresa.com", "mala-clave-mala")
    assert db.autenticar("ana@empresa.com", CLAVE) is None
    token, _ = db.solicitar_restablecimiento("ana@empresa.com")
    db.restablecer(token, NUEVA)
    assert db.autenticar("ana@empresa.com", NUEVA) is not None


def test_eliminar_usuario_borra_sus_tokens(db):
    token, _ = db.solicitar_restablecimiento("ana@empresa.com")
    uid = db.autenticar("ana@empresa.com", CLAVE)["id"]
    db.eliminar_usuario(uid)
    with pytest.raises(ErrorCuenta):
        db.restablecer(token, NUEVA)


# ---------- Correo ----------
def test_sin_smtp_no_envia(monkeypatch):
    for k in ("SMTP_HOST", "SMTP_USER", "VALORIX_CORREO_CONSOLA"):
        monkeypatch.delenv(k, raising=False)
    assert not valorix_correo.configurado()
    assert valorix_correo.enviar_restablecimiento("a@b.co", "Ana", "tok") is False


def test_modo_consola_imprime_el_enlace(monkeypatch, capsys):
    monkeypatch.setenv("VALORIX_CORREO_CONSOLA", "1")
    monkeypatch.setenv("VALORIX_URL_APP", "https://app.ejemplo.co/")
    assert valorix_correo.enviar_restablecimiento("a@b.co", "Ana", "tok-1") is True
    assert "https://app.ejemplo.co/?restablecer=tok-1" in capsys.readouterr().err


def test_smtp_envia_con_starttls(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.ejemplo.co")
    monkeypatch.setenv("SMTP_USER", "noreply@ejemplo.co")
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    monkeypatch.delenv("VALORIX_CORREO_CONSOLA", raising=False)
    with mock.patch("valorix_correo.smtplib.SMTP") as smtp:
        assert valorix_correo.enviar_restablecimiento("ana@empresa.com", "Ana", "tok") is True
    s = smtp.return_value.__enter__.return_value
    s.starttls.assert_called_once()
    msg = s.send_message.call_args[0][0]
    assert msg["To"] == "ana@empresa.com" and "?restablecer=tok" in msg.get_content()


def test_fallo_smtp_devuelve_false(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.ejemplo.co")
    monkeypatch.setenv("SMTP_USER", "noreply@ejemplo.co")
    with mock.patch("valorix_correo.smtplib.SMTP", side_effect=OSError("sin red")):
        assert valorix_correo.enviar_restablecimiento("a@b.co", "Ana", "tok") is False
