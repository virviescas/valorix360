"""Pruebas de cuentas, empresas y diagnósticos guardados."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valorix_db import MAX_FALLOS, Almacen, ErrorCuenta  # noqa: E402

CLAVE = "una-clave-segura-123"


@pytest.fixture
def db(tmp_path):
    return Almacen(tmp_path / "t.db")


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
    with db._con() as con:
        guardada = con.execute("SELECT clave FROM usuarios").fetchone()["clave"]
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
    with db._con() as con:
        pasado = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        con.execute("UPDATE usuarios SET bloqueado_hasta = ?", (pasado,))
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
