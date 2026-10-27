import pytest

import valorix_config
from valorix_config import ErrorConfiguracion, config_value, validar_configuracion_produccion


def test_config_value_prefers_environment(monkeypatch):
    monkeypatch.setenv("VALORIX_TEST_CONFIG", "environment")
    monkeypatch.setattr(valorix_config, "_streamlit_secrets", lambda: {"VALORIX_TEST_CONFIG": "secret"})

    assert config_value("VALORIX_TEST_CONFIG") == "environment"


def test_config_value_uses_streamlit_secret(monkeypatch):
    monkeypatch.delenv("VALORIX_TEST_CONFIG", raising=False)
    monkeypatch.setattr(valorix_config, "_streamlit_secrets", lambda: {"VALORIX_TEST_CONFIG": "secret"})

    assert config_value("VALORIX_TEST_CONFIG") == "secret"


def test_config_value_uses_default_without_secret(monkeypatch):
    monkeypatch.delenv("VALORIX_TEST_CONFIG", raising=False)
    monkeypatch.setattr(valorix_config, "_streamlit_secrets", lambda: {})

    assert config_value("VALORIX_TEST_CONFIG", "default") == "default"


def test_configuracion_local_no_exige_servicios_de_produccion(monkeypatch):
    monkeypatch.setenv("VALORIX_ENTORNO", "local")

    validar_configuracion_produccion()


def test_configuracion_produccion_exige_almacenamiento_y_url_segura(monkeypatch):
    monkeypatch.setenv("VALORIX_ENTORNO", "produccion")
    monkeypatch.setenv("VALORIX_CUENTAS", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("VALORIX_URL_APP", "http://app.example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "mailer@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")

    with pytest.raises(ErrorConfiguracion, match="DATABASE_URL"):
        validar_configuracion_produccion()


def test_configuracion_produccion_rechaza_correo_por_consola(monkeypatch):
    monkeypatch.setenv("VALORIX_ENTORNO", "produccion")
    monkeypatch.setenv("VALORIX_CUENTAS", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.example.com/app")
    monkeypatch.setenv("VALORIX_URL_APP", "https://app.example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "mailer@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("VALORIX_CORREO_CONSOLA", "1")

    with pytest.raises(ErrorConfiguracion, match="VALORIX_CORREO_CONSOLA"):
        validar_configuracion_produccion()