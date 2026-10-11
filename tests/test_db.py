"""Pruebas de cuentas, empresas y diagnósticos guardados.

Por defecto corren sobre SQLite. Con TEST_DATABASE_URL (PostgreSQL de prueba, se BORRAN sus tablas) corren también sobre él.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valorix_db import MAX_FALLOS, Almacen, ErrorCuenta, metadata, url_base  # noqa: E402

CLAVE = "una-clave-segura-123"


@pytest.fixture(params=["sqlite"] + (["postgres"] if os.environ.get("TEST_DATABASE_URL") else []))
def db(request, tmp_path):
    if request.param == "sqlite":
        yield Almacen(tmp_path / "t.db")
        return
    almacen = Almacen(url=os.environ["TEST_DATABASE_URL"])
    metadata.drop_all(almacen.engine)
    metadata.create_all(almacen.engine)
    yield almacen
    metadata.drop_all(almacen.engine)


def _usuario(db, correo="ana@empresa.com"):
    return db.crear_usuario(correo, "Ana", CLAVE, True)


def test_crear_y_autenticar(db):
    uid = _usuario(db)
    u = db.autenticar("ANA@empresa.com ", CLAVE)
    assert u and u["id"] == uid and u["correo"] == "ana@empresa.com"
    assert db.autenticar("ana@empresa.com", "otra-clave-distinta") is None
    assert db.autenticar("nadie@empresa.com", CLAVE) is None


def test_la_clave_no_se_guarda_en_claro(db):
    _usuario(db)
    with db.engine.connect() as con:
        guardada = con.execute(text("SELECT clave FROM usuarios")).scalar()
    assert CLAVE not in guardada and guardada.startswith("scrypt$")


@pytest.mark.parametrize("correo,nombre,clave,consent", [
    ("sin-arroba", "Ana", CLAVE, True), ("a@b.co", "A", CLAVE, True),
    ("a@b.co", "Ana", "corta", True), ("a@b.co", "Ana", CLAVE, False)])
def test_validaciones_de_registro(db, correo, nombre, clave, consent):
    with pytest.raises(ErrorCuenta):
        db.crear_usuario(correo, nombre, clave, consent)


def test_correo_duplicado_no_se_permite(db):
    _usuario(db)
    with pytest.raises(ErrorCuenta):
        _usuario(db)


def test_bloqueo_tras_intentos_fallidos(db):
    _usuario(db)
    for _ in range(MAX_FALLOS):
        assert db.autenticar("ana@empresa.com", "mala-clave-mala") is None
    assert db.autenticar("ana@empresa.com", CLAVE) is None  # bloqueada aunque la clave sea correcta
    with db.engine.begin() as con:
        pasado = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        con.execute(text("UPDATE usuarios SET bloqueado_hasta = :b"), {"b": pasado})
    assert db.autenticar("ana@empresa.com", CLAVE) is not None


def test_guardar_y_cargar_diagnostico(db):
    uid = _usuario(db)
    eid = db.crear_empresa(uid, "Mi Pyme")
    datos = {"salida": {"ingresos": [100.5, 90.0], "capital": [None, None]}, "tilde": "ñandú"}
    did = db.guardar(uid, eid, "Corte junio", "Comercio", datos)
    assert db.cargar(uid, did)["datos"] == datos
    assert [d["nombre"] for d in db.listar(uid, eid)] == ["Corte junio"]


def test_un_usuario_no_accede_a_datos_de_otro(db):
    a, b = _usuario(db), _usuario(db, "beto@empresa.com")
    ea = db.crear_empresa(a, "Empresa A")
    did = db.guardar(a, ea, "D", "General", {"x": 1})
    assert db.cargar(b, did) is None
    assert db.listar(b, ea) == []
    with pytest.raises(ErrorCuenta):
        db.guardar(b, ea, "intruso", "General", {})
    db.eliminar_diagnostico(b, did)
    db.eliminar_empresa(b, ea)
    assert db.cargar(a, did) is not None
    assert db.listar_empresas(b) == []


def test_empresa_duplicada_y_vacia(db):
    uid = _usuario(db)
    db.crear_empresa(uid, "Mi Pyme")
    with pytest.raises(ErrorCuenta):
        db.crear_empresa(uid, "Mi Pyme")
    with pytest.raises(ErrorCuenta):
        db.crear_empresa(uid, " ")


def test_eliminar_usuario_borra_todo(db):
    uid = _usuario(db)
    eid = db.crear_empresa(uid, "Mi Pyme")
    did = db.guardar(uid, eid, "D", "General", {"x": 1})
    db.eliminar_usuario(uid)
    assert db.cargar(uid, did) is None and db.listar_empresas(uid) == []
    assert db.autenticar("ana@empresa.com", CLAVE) is None


# ---------- Compatibilidad con PostgreSQL (sin servidor: se valida el SQL generado) ----------
def test_esquema_compila_para_postgresql():
    dialecto = postgresql.dialect()
    ddl = " ".join(str(CreateTable(t).compile(dialect=dialecto)) for t in metadata.sorted_tables)
    assert "SERIAL" in ddl or "GENERATED" in ddl
    assert "ON DELETE CASCADE" in ddl


@pytest.mark.parametrize("entrada,esperado", [
    ("postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
    ("postgresql://u:p@h/d?sslmode=require", "postgresql+psycopg://u:p@h/d?sslmode=require"),
    ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d")])
def test_url_de_postgres_se_normaliza(entrada, esperado):
    assert url_base(url=entrada) == esperado


def test_database_url_tiene_prioridad_sobre_sqlite(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/d")
    assert url_base(tmp_path / "x.db").startswith("postgresql+psycopg://")
    monkeypatch.delenv("DATABASE_URL")
    assert url_base(tmp_path / "x.db").startswith("sqlite:///")
