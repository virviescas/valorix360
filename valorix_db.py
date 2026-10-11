"""VALORIX360 · Cuentas de usuario, empresas y diagnósticos guardados (SQLite).

Toda lectura o escritura se filtra por `usuario_id`, de modo que un usuario nunca ve datos de otro.
Las claves se guardan con scrypt (sal aleatoria) y hay bloqueo temporal tras varios intentos fallidos.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUTA_DEFECTO = Path(os.environ.get("VALORIX_DB") or Path(__file__).with_name("data") / "valorix.db")
MAX_FALLOS = 5
BLOQUEO_MIN = 15
MIN_CLAVE = 10
MAX_JSON = 2_000_000
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY, correo TEXT NOT NULL UNIQUE, nombre TEXT NOT NULL, clave TEXT NOT NULL,
    fallos INTEGER NOT NULL DEFAULT 0, bloqueado_hasta TEXT, creado TEXT NOT NULL, consentimiento TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS empresas (
    id INTEGER PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL, creado TEXT NOT NULL, UNIQUE (usuario_id, nombre));
CREATE TABLE IF NOT EXISTS diagnosticos (
    id INTEGER PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    empresa_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL, sector TEXT NOT NULL, creado TEXT NOT NULL, datos TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_diag_empresa ON diagnosticos (usuario_id, empresa_id, creado);
"""


class ErrorCuenta(ValueError):
    """Error de validación apto para mostrarlo al usuario."""


def _ahora():
    return datetime.now(timezone.utc)


def _hash(clave, sal=None):
    sal = sal or secrets.token_bytes(16)
    h = hashlib.scrypt(clave.encode(), salt=sal, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(sal).decode() + "$" + base64.b64encode(h).decode()


def _verificar(clave, almacenado):
    try:
        _, s, h = almacenado.split("$")
        sal, esperado = base64.b64decode(s), base64.b64decode(h)
    except ValueError:
        return False
    calculado = hashlib.scrypt(clave.encode(), salt=sal, n=2 ** 14, r=8, p=1, dklen=32)
    return hmac.compare_digest(calculado, esperado)


_HASH_FALSO = _hash("clave-inexistente")  # iguala el tiempo de respuesta cuando el correo no existe


class Almacen:
    def __init__(self, ruta=None):
        self.ruta = Path(ruta or RUTA_DEFECTO)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as con:
            con.executescript(ESQUEMA)

    @contextmanager
    def _con(self):
        con = sqlite3.connect(self.ruta, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ---------------- usuarios ----------------
    def crear_usuario(self, correo, nombre, clave, consentimiento):
        correo, nombre = (correo or "").strip().lower(), (nombre or "").strip()
        if not EMAIL_RE.match(correo):
            raise ErrorCuenta("Escribe un correo válido.")
        if not 2 <= len(nombre) <= 100:
            raise ErrorCuenta("Escribe tu nombre (entre 2 y 100 caracteres).")
        if len(clave or "") < MIN_CLAVE:
            raise ErrorCuenta(f"La contraseña debe tener al menos {MIN_CLAVE} caracteres.")
        if not consentimiento:
            raise ErrorCuenta("Debes autorizar el tratamiento de tus datos para crear la cuenta.")
        try:
            with self._con() as con:
                cur = con.execute("INSERT INTO usuarios (correo, nombre, clave, creado, consentimiento) VALUES (?,?,?,?,?)",
                                  (correo, nombre, _hash(clave), _ahora().isoformat(), _ahora().isoformat()))
                return cur.lastrowid
        except sqlite3.IntegrityError:
            raise ErrorCuenta("No se pudo crear la cuenta con esos datos.") from None

    def autenticar(self, correo, clave):
        """Devuelve dict(id, nombre, correo) o None. Mensaje único para no revelar si el correo existe."""
        correo = (correo or "").strip().lower()
        with self._con() as con:
            u = con.execute("SELECT * FROM usuarios WHERE correo = ?", (correo,)).fetchone()
            if u is None:
                _verificar(clave or "", _HASH_FALSO)
                return None
            if u["bloqueado_hasta"] and datetime.fromisoformat(u["bloqueado_hasta"]) > _ahora():
                return None
            if _verificar(clave or "", u["clave"]):
                con.execute("UPDATE usuarios SET fallos = 0, bloqueado_hasta = NULL WHERE id = ?", (u["id"],))
                return dict(id=u["id"], nombre=u["nombre"], correo=u["correo"])
            fallos = u["fallos"] + 1
            bloqueo = (_ahora() + timedelta(minutes=BLOQUEO_MIN)).isoformat() if fallos >= MAX_FALLOS else None
            con.execute("UPDATE usuarios SET fallos = ?, bloqueado_hasta = ? WHERE id = ?",
                        (0 if bloqueo else fallos, bloqueo, u["id"]))
            return None

    def eliminar_usuario(self, uid):
        """Borra la cuenta y todos sus datos (derecho de supresión)."""
        with self._con() as con:
            con.execute("DELETE FROM usuarios WHERE id = ?", (uid,))

    # ---------------- empresas ----------------
    def crear_empresa(self, uid, nombre):
        nombre = (nombre or "").strip()
        if not 2 <= len(nombre) <= 120:
            raise ErrorCuenta("Escribe el nombre de la empresa (entre 2 y 120 caracteres).")
        try:
            with self._con() as con:
                return con.execute("INSERT INTO empresas (usuario_id, nombre, creado) VALUES (?,?,?)",
                                   (uid, nombre, _ahora().isoformat())).lastrowid
        except sqlite3.IntegrityError:
            raise ErrorCuenta("Ya tienes una empresa con ese nombre.") from None

    def listar_empresas(self, uid):
        with self._con() as con:
            return [dict(r) for r in con.execute("SELECT id, nombre FROM empresas WHERE usuario_id = ? ORDER BY nombre", (uid,))]

    def eliminar_empresa(self, uid, eid):
        with self._con() as con:
            con.execute("DELETE FROM empresas WHERE id = ? AND usuario_id = ?", (eid, uid))

    # ---------------- diagnósticos ----------------
    def guardar(self, uid, eid, nombre, sector, datos):
        texto = json.dumps(datos, ensure_ascii=False, default=str)
        if len(texto) > MAX_JSON:
            raise ErrorCuenta("El diagnóstico es demasiado grande para guardarlo.")
        with self._con() as con:
            if not con.execute("SELECT 1 FROM empresas WHERE id = ? AND usuario_id = ?", (eid, uid)).fetchone():
                raise ErrorCuenta("La empresa no existe.")
            return con.execute("INSERT INTO diagnosticos (usuario_id, empresa_id, nombre, sector, creado, datos) VALUES (?,?,?,?,?,?)",
                               (uid, eid, (nombre or "Diagnóstico")[:150], sector, _ahora().isoformat(), texto)).lastrowid

    def listar(self, uid, eid):
        with self._con() as con:
            return [dict(r) for r in con.execute(
                "SELECT id, nombre, sector, creado FROM diagnosticos WHERE usuario_id = ? AND empresa_id = ? ORDER BY creado DESC",
                (uid, eid))]

    def cargar(self, uid, did):
        with self._con() as con:
            r = con.execute("SELECT id, nombre, sector, creado, datos FROM diagnosticos WHERE id = ? AND usuario_id = ?",
                            (did, uid)).fetchone()
        return None if r is None else dict(id=r["id"], nombre=r["nombre"], sector=r["sector"], creado=r["creado"],
                                           datos=json.loads(r["datos"]))

    def eliminar_diagnostico(self, uid, did):
        with self._con() as con:
            con.execute("DELETE FROM diagnosticos WHERE id = ? AND usuario_id = ?", (did, uid))
