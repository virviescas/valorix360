"""VALORIX360 · Interfaz de cuentas: acceso, empresas, historial y comparación de diagnósticos guardados."""
import hmac
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from valorix_db import ErrorCuenta
from valorix_motor import ADIC_SPEC, calcular, fmt_valor

AGENTES = ("contable", "financiero", "cumplimiento")
LOGO_SVG = Path(__file__).with_name("assets").joinpath("logo.svg").read_text(encoding="utf-8").strip().replace("<svg ", "<svg width='26' height='26' ", 1)
CONSENTIMIENTO = ("Autorizo a Valorix360 el tratamiento de mis datos personales y de la información financiera que cargue, "
                  "para prestar el servicio, conforme a la Ley 1581 de 2012. Puedo eliminar mi cuenta y mis datos cuando quiera.")


def _fecha(iso):
    return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y %H:%M")


# ---------------- Acceso ----------------
def acceso(db):
    """Devuelve el usuario autenticado; si no hay sesión muestra ingreso o registro y detiene el script."""
    if st.session_state.get("usuario"):
        return st.session_state["usuario"]
    st.markdown("<div class='vx-hero'><div class='vx-logo'>" + LOGO_SVG + "VALORIX <span>360</span></div>"
                "<div class='vx-eyebrow'>Acceso</div><h1>Ingresa a tu cuenta</h1>"
                "<p>Guarda tus diagnósticos, organiza varias empresas y compara su evolución.</p></div>", unsafe_allow_html=True)
    t_in, t_reg = st.tabs(["Ingresar", "Crear cuenta"])
    with t_in, st.form("ingreso"):
        correo = st.text_input("Correo")
        clave = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar", type="primary"):
            u = db.autenticar(correo, clave)
            if u:
                st.session_state["usuario"] = u
                st.rerun()
            st.error("Correo o contraseña incorrectos, o cuenta bloqueada temporalmente.")
    with t_reg, st.form("registro"):
        nombre = st.text_input("Nombre")
        correo_r = st.text_input("Correo", key="correo_registro")
        clave_r = st.text_input("Contraseña (mínimo 10 caracteres)", type="password", key="clave_registro")
        codigo_req = os.environ.get("VALORIX_CODIGO_INVITACION")
        codigo = st.text_input("Código de invitación", type="password") if codigo_req else None
        acepto = st.checkbox(CONSENTIMIENTO)
        if st.form_submit_button("Crear cuenta", type="primary"):
            try:
                if codigo_req and not hmac.compare_digest((codigo or "").encode(), codigo_req.encode()):
                    raise ErrorCuenta("Código de invitación incorrecto.")
                db.crear_usuario(correo_r, nombre, clave_r, acepto)
                st.success("Cuenta creada. Ya puedes ingresar desde la pestaña «Ingresar».")
            except ErrorCuenta as e:
                st.error(str(e))
    st.stop()


def barra_cuenta(db, usuario):
    """Dibuja el bloque de cuenta en la barra lateral y devuelve el id de la empresa activa (o None)."""
    st.header("Cuenta")
    st.caption(f"{usuario['nombre']} · {usuario['correo']}")
    empresas = db.listar_empresas(usuario["id"])
    empresa_id = None
    if "empresa_pendiente" in st.session_state:  # empresa recién creada: se fija antes de crear el selector
        st.session_state["empresa_id"] = st.session_state.pop("empresa_pendiente")
    if empresas:
        empresa_id = st.selectbox("Empresa", [e["id"] for e in empresas], format_func=lambda i: next(e["nombre"] for e in empresas if e["id"] == i),
                                  key="empresa_id")
    else:
        st.info("Crea tu primera empresa para guardar diagnósticos.")
    with st.expander("Nueva empresa", expanded=not empresas), st.form("nueva_empresa", clear_on_submit=True):
        nombre = st.text_input("Nombre de la empresa")
        if st.form_submit_button("Crear"):
            try:
                st.session_state["empresa_pendiente"] = db.crear_empresa(usuario["id"], nombre)
                st.rerun()
            except ErrorCuenta as e:
                st.error(str(e))
    if st.button("Cerrar sesión"):
        st.session_state.clear()
        st.rerun()
    with st.expander("Eliminar mi cuenta y mis datos"):
        st.caption("Borra tu cuenta, tus empresas y todos los diagnósticos guardados. No se puede deshacer.")
        if st.checkbox("Entiendo que es definitivo") and st.button("Eliminar todo"):
            db.eliminar_usuario(usuario["id"])
            st.session_state.clear()
            st.rerun()
    st.divider()
    return empresa_id


# ---------------- Guardar y restaurar ----------------
def empaquetar(res, notas, hechos, adic, sector, salida, nombre):
    return dict(version=1, nombre=nombre, sector=sector, salida=salida, adic=adic, validaciones=res["validaciones"],
                avisos=res["avisos"], meta=res["meta"], unidad=res["unidad"], years=res["years"], hechos=hechos, notas=notas)


def _restaurar(db, usuario_id, did):
    """Callback: carga un diagnóstico guardado en la sesión (corre antes de dibujar los widgets)."""
    g = db.cargar(usuario_id, did)
    if g is None:
        return
    d = g["datos"]
    res = dict(datos={}, log=[], sin_mapear=[], avisos=d["avisos"] + [f"Diagnóstico guardado el {_fecha(g['creado'])}."], factor=1.0,
               unidad=d["unidad"], i_act=0, years=d["years"], fecha_er=None, notas_lineas=[], salida=d["salida"], meta=d["meta"],
               validaciones=d["validaciones"])
    nombre = d["nombre"]
    st.session_state.update(res=res, notas=d["notas"], hechos=d["hechos"], nombre=nombre, chat={a: [] for a in AGENTES}, sector=g["sector"])
    for k, _, _, tipo, _ in ADIC_SPEC:
        v = d["adic"].get(k)
        st.session_state[f"adic_{nombre}_{k}"] = None if v is None else (v * 100 if tipo == "pct" else v)
    st.session_state.pop("xlsx", None)
    st.session_state.pop("pdf", None)


# ---------------- Pestaña Historial ----------------
def pestana_historial(db, usuario, empresa_id, paquete, nombre_defecto, sector):
    if empresa_id is None:
        st.info("Crea o elige una empresa en la barra lateral para guardar y ver diagnósticos.")
        return
    uid = usuario["id"]
    if paquete is not None:  # sin diagnóstico cargado solo se listan los guardados
        st.subheader("Guardar este diagnóstico")
        c1, c2 = st.columns([3, 1])
        nombre = c1.text_input("Nombre", value=f"{nombre_defecto} · {datetime.now():%d/%m/%Y}",
                               key=f"nombre_guardado_{nombre_defecto}", max_chars=150)
        c2.write("")
        if c2.button("Guardar", type="primary", key="guardar_diag"):
            try:
                db.guardar(uid, empresa_id, nombre, sector, paquete())
                st.success("Diagnóstico guardado.")
            except ErrorCuenta as e:
                st.error(str(e))
    guardados = db.listar(uid, empresa_id)
    st.subheader("Diagnósticos guardados")
    if not guardados:
        st.caption("Aún no hay diagnósticos guardados para esta empresa.")
        return
    for g in guardados:
        a, b, c, d, e = st.columns([4, 2, 2, 1, 1])
        a.write(g["nombre"])
        b.caption(_fecha(g["creado"]))
        c.caption(g["sector"])
        d.button("Abrir", key=f"abrir_{g['id']}", on_click=_restaurar, args=(db, uid, g["id"]))
        with e.popover("🗑"):
            st.write("¿Eliminar este diagnóstico?")
            if st.button("Sí, eliminar", key=f"borrar_{g['id']}"):
                db.eliminar_diagnostico(uid, g["id"])
                st.rerun()
    if len(guardados) >= 2:
        st.subheader("Comparar dos diagnósticos")
        nombres = {g["id"]: f"{g['nombre']} ({_fecha(g['creado'])})" for g in guardados}
        x, y = st.columns(2)
        antes = x.selectbox("Anterior", list(nombres), index=len(nombres) - 1, format_func=nombres.get, key="cmp_a")
        despues = y.selectbox("Reciente", list(nombres), index=0, format_func=nombres.get, key="cmp_b")
        filas = _comparar(db, uid, antes, despues)
        if filas:
            st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)


def _comparar(db, uid, id_a, id_b):
    ga, gb = db.cargar(uid, id_a), db.cargar(uid, id_b)
    if ga is None or gb is None:
        return []
    ca = calcular(ga["datos"]["salida"], ga["datos"]["adic"], gb["sector"])["m"]  # mismo sector para que sean comparables
    cb = calcular(gb["datos"]["salida"], gb["datos"]["adic"], gb["sector"])["m"]
    filas = []
    for k, mb in cb.items():
        ma = ca.get(k)
        if ma is None or ma["actual"] is None or mb["actual"] is None or mb["fmt"] not in ("x", "pct", "m", "dias"):
            continue
        delta = mb["actual"] - ma["actual"]
        filas.append({"Indicador": mb["nombre"], "Anterior": fmt_valor(ma["actual"], mb["fmt"]), "Reciente": fmt_valor(mb["actual"], mb["fmt"]),
                      "Cambio": ("+" if delta > 0 else "") + fmt_valor(delta, mb["fmt"])})
    return filas
