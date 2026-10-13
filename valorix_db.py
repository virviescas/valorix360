"""VALORIX360 · Cuentas de usuario, empresas y diagnósticos guardados.

Usa SQLite por defecto (archivo local) o PostgreSQL si se define DATABASE_URL, con las mismas consultas (SQLAlchemy Core).
Toda lectura o escritura se filtra por `usuario_id`, de modo que un usuario nunca ve datos de otro.
Las claves se guardan con scrypt (sal aleatoria) y hay bloqueo temporal tras varios intentos fallidos.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import (Column, ForeignKey, Index, Integer, MetaData, Table, Text, UniqueConstraint, create_engine, delete, event,
                        insert, select, update)
from sqlalchemy.exc import IntegrityError

from valorix_config import config_value

RUTA_DEFECTO = Path(config_value("VALORIX_DB") or Path(__file__).with_name("data") / "valorix.db")
MAX_FALLOS = 5
BLOQUEO_MIN = 15
MIN_CLAVE = 10
MAX_JSON = 2_000_000
VIGENCIA_TOKEN_MIN = 30
MAX_SOLICITUDES_HORA = 3
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")

metadata = MetaData()
usuarios = Table(
    "usuarios", metadata,
    Column("id", Integer, primary_key=True), Column("correo", Text, nullable=False, unique=True),
    Column("nombre", Text, nullable=False), Column("clave", Text, nullable=False),
    Column("fallos", Integer, nullable=False, server_default="0"), Column("bloqueado_hasta", Text),
    Column("creado", Text, nullable=False), Column("consentimiento", Text, nullable=False))
empresas = Table(
    "empresas", metadata,
    Column("id", Integer, primary_key=True), Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
    Column("nombre", Text, nullable=False), Column("creado", Text, nullable=False), UniqueConstraint("usuario_id", "nombre"))
diagnosticos = Table(
    "diagnosticos", metadata,
    Column("id", Integer, primary_key=True), Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
    Column("empresa_id", Integer, ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False),
    Column("nombre", Text, nullable=False), Column("sector", Text, nullable=False), Column("creado", Text, nullable=False),
    Column("datos", Text, nullable=False), Index("ix_diag_empresa", "usuario_id", "empresa_id", "creado"))


restablecimientos = Table(
    "restablecimientos", metadata,
    Column("id", Integer, primary_key=True), Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
    Column("token_hash", Text, nullable=False, unique=True), Column("expira", Text, nullable=False),
    Column("usado", Integer, nullable=False, server_default="0"), Column("creado", Text, nullable=False))


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


def url_base(ruta=None, url=None):
    """URL SQLAlchemy: DATABASE_URL (PostgreSQL) si existe; si no, un archivo SQLite."""
    url = url or config_value("DATABASE_URL")
    if not url:
        ruta = Path(ruta or RUTA_DEFECTO)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{ruta.as_posix()}"
    for prefijo in ("postgres://", "postgresql://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url[len(prefijo):]
    return url


class Almacen:
    def __init__(self, ruta=None, url=None):
        self.engine = create_engine(url_base(ruta, url), pool_pre_ping=True)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys = ON"))
        metadata.create_all(self.engine)

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
        ahora = _ahora().isoformat()
        try:
            with self.engine.begin() as con:
                r = con.execute(insert(usuarios).values(correo=correo, nombre=nombre, clave=_hash(clave), creado=ahora,
                                                        consentimiento=ahora))
                return r.inserted_primary_key[0]
        except IntegrityError:
            raise ErrorCuenta("No se pudo crear la cuenta con esos datos.") from None

    def autenticar(self, correo, clave):
        """Devuelve dict(id, nombre, correo) o None. Mensaje único para no revelar si el correo existe."""
        correo = (correo or "").strip().lower()
        with self.engine.begin() as con:
            u = con.execute(select(usuarios).where(usuarios.c.correo == correo)).mappings().first()
            if u is None:
                _verificar(clave or "", _HASH_FALSO)
                return None
            if u["bloqueado_hasta"] and datetime.fromisoformat(u["bloqueado_hasta"]) > _ahora():
                return None
            if _verificar(clave or "", u["clave"]):
                con.execute(update(usuarios).where(usuarios.c.id == u["id"]).values(fallos=0, bloqueado_hasta=None))
                return dict(id=u["id"], nombre=u["nombre"], correo=u["correo"])
            fallos = u["fallos"] + 1
            bloqueo = (_ahora() + timedelta(minutes=BLOQUEO_MIN)).isoformat() if fallos >= MAX_FALLOS else None
            con.execute(update(usuarios).where(usuarios.c.id == u["id"]).values(fallos=0 if bloqueo else fallos, bloqueado_hasta=bloqueo))
            return None

    # ---------------- recuperación de contraseña ----------------
    @staticmethod
    def _huella(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def solicitar_restablecimiento(self, correo):
        """Devuelve (token, nombre) si el correo existe y no superó el límite; si no, None. El token solo se guarda como huella."""
        correo = (correo or "").strip().lower()
        with self.engine.begin() as con:
            u = con.execute(select(usuarios.c.id, usuarios.c.nombre).where(usuarios.c.correo == correo)).mappings().first()
            if u is None:
                return None
            hace_hora = (_ahora() - timedelta(hours=1)).isoformat()
            recientes = con.execute(select(restablecimientos.c.id).where(restablecimientos.c.usuario_id == u["id"],
                                                                          restablecimientos.c.creado > hace_hora)).all()
            if len(recientes) >= MAX_SOLICITUDES_HORA:
                return None
            token = secrets.token_urlsafe(32)
            con.execute(insert(restablecimientos).values(
                usuario_id=u["id"], token_hash=self._huella(token), creado=_ahora().isoformat(),
                expira=(_ahora() + timedelta(minutes=VIGENCIA_TOKEN_MIN)).isoformat()))
            return token, u["nombre"]

    def restablecer(self, token, nueva_clave):
        """Cambia la contraseña con un token vigente y sin usar; el token solo sirve una vez."""
        if len(nueva_clave or "") < MIN_CLAVE:
            raise ErrorCuenta(f"La contraseña debe tener al menos {MIN_CLAVE} caracteres.")
        with self.engine.begin() as con:
            r = con.execute(select(restablecimientos).where(restablecimientos.c.token_hash == self._huella(token or ""))).mappings().first()
            if r is None or r["usado"] or datetime.fromisoformat(r["expira"]) < _ahora():
                raise ErrorCuenta("El enlace no es válido o ya venció. Solicita uno nuevo.")
            con.execute(update(usuarios).where(usuarios.c.id == r["usuario_id"]).values(clave=_hash(nueva_clave), fallos=0, bloqueado_hasta=None))
            con.execute(update(restablecimientos).where(restablecimientos.c.usuario_id == r["usuario_id"]).values(usado=1))

    def eliminar_usuario(self, uid):
        """Borra la cuenta y todos sus datos (derecho de supresión)."""
        with self.engine.begin() as con:
            con.execute(delete(restablecimientos).where(restablecimientos.c.usuario_id == uid))
            con.execute(delete(diagnosticos).where(diagnosticos.c.usuario_id == uid))
            con.execute(delete(empresas).where(empresas.c.usuario_id == uid))
            con.execute(delete(usuarios).where(usuarios.c.id == uid))

    # ---------------- empresas ----------------
    def crear_empresa(self, uid, nombre):
        nombre = (nombre or "").strip()
        if not 2 <= len(nombre) <= 120:
            raise ErrorCuenta("Escribe el nombre de la empresa (entre 2 y 120 caracteres).")
        try:
            with self.engine.begin() as con:
                r = con.execute(insert(empresas).values(usuario_id=uid, nombre=nombre, creado=_ahora().isoformat()))
                return r.inserted_primary_key[0]
        except IntegrityError:
            raise ErrorCuenta("Ya tienes una empresa con ese nombre.") from None

    def listar_empresas(self, uid):
        with self.engine.connect() as con:
            q = select(empresas.c.id, empresas.c.nombre).where(empresas.c.usuario_id == uid).order_by(empresas.c.nombre)
            return [dict(r) for r in con.execute(q).mappings()]

    def eliminar_empresa(self, uid, eid):
        with self.engine.begin() as con:
            if con.execute(select(empresas.c.id).where(empresas.c.id == eid, empresas.c.usuario_id == uid)).first():
                con.execute(delete(diagnosticos).where(diagnosticos.c.empresa_id == eid, diagnosticos.c.usuario_id == uid))
                con.execute(delete(empresas).where(empresas.c.id == eid, empresas.c.usuario_id == uid))

    # ---------------- diagnósticos ----------------
    def guardar(self, uid, eid, nombre, sector, datos):
        texto = json.dumps(datos, ensure_ascii=False, default=str)
        if len(texto) > MAX_JSON:
            raise ErrorCuenta("El diagnóstico es demasiado grande para guardarlo.")
        with self.engine.begin() as con:
            if not con.execute(select(empresas.c.id).where(empresas.c.id == eid, empresas.c.usuario_id == uid)).first():
                raise ErrorCuenta("La empresa no existe.")
            r = con.execute(insert(diagnosticos).values(usuario_id=uid, empresa_id=eid, nombre=(nombre or "Diagnóstico")[:150],
                                                        sector=sector, creado=_ahora().isoformat(), datos=texto))
            return r.inserted_primary_key[0]

    def listar(self, uid, eid):
        with self.engine.connect() as con:
            q = (select(diagnosticos.c.id, diagnosticos.c.nombre, diagnosticos.c.sector, diagnosticos.c.creado)
                 .where(diagnosticos.c.usuario_id == uid, diagnosticos.c.empresa_id == eid).order_by(diagnosticos.c.creado.desc()))
            return [dict(r) for r in con.execute(q).mappings()]

    def cargar(self, uid, did):
        with self.engine.connect() as con:
            r = con.execute(select(diagnosticos).where(diagnosticos.c.id == did, diagnosticos.c.usuario_id == uid)).mappings().first()
        return None if r is None else dict(id=r["id"], nombre=r["nombre"], sector=r["sector"], creado=r["creado"],
                                           datos=json.loads(r["datos"]))

    def eliminar_diagnostico(self, uid, did):
        with self.engine.begin() as con:
            con.execute(delete(diagnosticos).where(diagnosticos.c.id == did, diagnosticos.c.usuario_id == uid))
