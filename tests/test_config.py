import valorix_config
from valorix_config import config_value


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