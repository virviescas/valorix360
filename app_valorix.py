"""
VALORIX360 · Aplicación web local (Streamlit)

Flujo: sube el PDF -> revisa las cifras -> completa supuestos -> diagnóstico con tres agentes ->
indicadores -> proyección -> conversación con los agentes -> descarga del Excel.

Ejecutar:   streamlit run app_valorix.py
Opcional:   VALORIX_PASSWORD="clave"            (acceso con contraseña)
            ANTHROPIC_API_KEY="..."             (agentes con IA; sin clave responden con reglas)
            VALORIX_MODELO="claude-sonnet-5-5"  (modelo de los agentes)
"""
import hmac
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from valorix_agentes import AVISO, NOMBRES_AGENTES, consultar_agente, construir_contexto
from valorix_extractor import consolidar, escribir_plantilla, extraer, segmentar_notas
from valorix_motor import (ADIC_SPEC, ESCENARIOS, calcular, extraer_hechos, fmt_valor, generar_hallazgos, mm, n,
                           proyectar)

ETIQUETAS = {
    "efectivo": "Efectivo y equivalentes", "cxc": "Cuentas por cobrar (clientes)", "inventarios": "Inventarios",
    "otros_ac": "Otros activos corrientes", "anc": "Activos no corrientes",
    "oblig_cp": "Obligaciones financieras de corto plazo", "proveedores": "Proveedores",
    "otros_pc": "Otros pasivos corrientes", "pnc": "Pasivo no corriente", "patrimonio": "Patrimonio",
    "ingresos": "Ingresos por ventas", "costo": "Costo de ventas",
    "gastos_op": "Gastos operativos (sin depreciación)", "da": "Depreciación y amortización",
    "gastos_fin": "Gastos financieros", "impuestos": "Impuestos", "cfo": "Flujo de caja operativo",
    "capex": "Inversión en activos fijos (Capex)", "servicio_deuda": "Servicio de la deuda",
    "dias": "Días del periodo", "deuda_lp": "Deuda financiera de largo plazo", "capital": "Capital social y primas",
}
ICONO = {"ok": "✅", "atencion": "⚠️", "riesgo": "🔴"}
ESTADO = {"Bien": "✅ Bien", "Revisar": "⚠️ Revisar", "n/d": "—"}
AGENTES = ("contable", "financiero", "cumplimiento")
PLANTILLA_DEFECTO = Path(__file__).with_name("valorix360_plantilla_diagnostico.xlsx")

st.set_page_config(page_title="Valorix360 · Diagnóstico financiero", page_icon="📈", layout="wide")

# ---------------- Acceso opcional ----------------
clave = os.environ.get("VALORIX_PASSWORD")
if clave and st.session_state.get("ok") is not True:
    st.title("Valorix360")
    ingreso = st.text_input("Contraseña", type="password")
    if ingreso and hmac.compare_digest(ingreso.encode(), clave.encode()):
        st.session_state["ok"] = True
        st.rerun()
    elif ingreso:
        st.error("Contraseña incorrecta")
    st.stop()

st.title("📈 Valorix360 · Diagnóstico financiero desde PDF")
st.caption("Los archivos se procesan en archivos temporales que se eliminan al terminar. Los estados financieros son "
           "confidenciales: úsalo solo en equipos y redes autorizados.")

# ---------------- Barra lateral ----------------
with st.sidebar:
    st.header("Opciones")
    unidad = st.selectbox("Unidad del PDF", ["Auto", "pesos", "miles", "millones"])
    dias_act = st.number_input("Días del periodo actual (0 = automático)", 0, 366, 0)
    dias_ant = st.number_input("Días del periodo anterior (0 = igual al actual)", 0, 366, 0)
    da_incluida = st.checkbox("La depreciación está dentro de los gastos operativos", value=True)
    plantilla_subida = st.file_uploader("Plantilla Excel (opcional)", type=["xlsx"])
    st.divider()
    usar_ia = st.checkbox("Agentes con IA", value=False,
                          help="Envía el diagnóstico (cifras y notas) a la API de Anthropic. Actívalo solo si el cliente lo autoriza.")
    if usar_ia and not os.environ.get("ANTHROPIC_API_KEY"):
        st.info("No hay ANTHROPIC_API_KEY: los agentes responderán con reglas.")

pdf = st.file_uploader("Estados financieros en PDF (con notas)", type=["pdf"])
FACTORES = {"pesos": 1e-6, "miles": 1e-3, "millones": 1.0}

if pdf and st.button("Procesar PDF", type="primary"):
    with st.spinner("Leyendo y organizando el PDF..."):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        try:
            tmp.write(pdf.getbuffer())
            tmp.close()
            res = extraer(tmp.name)
        finally:
            os.unlink(tmp.name)
        factor = FACTORES.get(unidad)
        consolidar(res, factor, dias_act or None, dias_ant or None, da_en_gastos=da_incluida)
        notas = segmentar_notas(res["notas_lineas"])
        st.session_state.update(res=res, notas=notas, nombre=Path(pdf.name).stem, chat={a: [] for a in AGENTES},
                                hechos=extraer_hechos(notas, factor if factor is not None else (res["factor"] or 1.0)))
        st.session_state.pop("xlsx", None)

res = st.session_state.get("res")
if res is None:
    st.info("Sube un PDF y pulsa **Procesar PDF**.")
    st.stop()
notas, hechos = st.session_state["notas"], st.session_state["hechos"]

tabs = st.tabs(["1 · Revisión", "2 · Datos", "3 · Supuestos", "4 · Diagnóstico", "5 · Indicadores",
                "6 · Proyección", "7 · Agentes", "8 · Notas y líneas sin mapear"])
t_rev, t_dat, t_sup, t_dia, t_ind, t_pro, t_age, t_not = tabs

# ---------------- 2. Datos editables ----------------
with t_dat:
    st.write("Corrige cualquier cifra antes del diagnóstico. Valores en **millones de COP**.")
    filas = []
    for k, etiqueta in ETIQUETAS.items():
        a, p = res["salida"].get(k, [None, None])
        filas.append({"clave": k, "Dato": etiqueta, "Actual": a, "Anterior": p,
                      "Origen": res["meta"].get(k, "Directo del PDF" if k in res["datos"] else "FALTA")})
    editado = st.data_editor(pd.DataFrame(filas).set_index("clave"), width="stretch", disabled=["Dato", "Origen"],
                             num_rows="fixed", column_config={"Actual": st.column_config.NumberColumn(format="%.2f"),
                                                              "Anterior": st.column_config.NumberColumn(format="%.2f")})
    salida_ed = {k: [None if pd.isna(f["Actual"]) else float(f["Actual"]), None if pd.isna(f["Anterior"]) else float(f["Anterior"])]
                 for k, f in editado.iterrows()}
    faltan = [ETIQUETAS[k] for k, v in salida_ed.items() if v[0] is None]
    if faltan:
        st.warning("Sin valor en el periodo actual: " + ", ".join(faltan))

# ---------------- 3. Supuestos ----------------
with t_sup:
    st.write("Datos que el PDF no trae. Todo es opcional, pero habilita LTM, covenants, WACC y EVA. "
             "Los covenants se prellenan con lo que se encontró en las notas.")
    adic = {}
    cols = st.columns(3)
    for i, (k, etiqueta, fila, tipo, defecto) in enumerate(ADIC_SPEC):
        d0 = hechos[k]["valor"] if k in hechos and k.startswith("cov_") else defecto
        d0 = d0 * 100 if (tipo == "pct" and d0 is not None) else d0
        with cols[i % 3]:
            v = st.number_input(etiqueta, value=None if d0 is None else float(d0),
                                key=f"adic_{st.session_state.get('nombre', '')}_{k}", step=0.5 if tipo == "pct" else 1.0)
        adic[k] = None if v is None else (v / 100 if tipo == "pct" else v)

# ---------------- Cálculo ----------------
calc = calcular(salida_ed, adic)
hall = generar_hallazgos(calc, hechos, res["validaciones"])
ctx = construir_contexto(calc, hall, notas, hechos, salida_ed, res["validaciones"])

# ---------------- 1. Revisión ----------------
with t_rev:
    c1, c2, c3 = st.columns(3)
    c1.metric("Unidad detectada", res["unidad"] or "No detectada")
    c2.metric("Periodos (columnas)", " / ".join(str(y) for y in res["years"] if y) or "No detectados")
    c3.metric("Notas encontradas", len(notas))
    for a in res["avisos"]:
        st.warning(a)
    if res["fecha_er"]:
        st.info(f"Corte del estado de resultados: {res['fecha_er']} → {res['salida']['dias'][0]} días. "
                "Confirma que la columna anterior sea el MISMO periodo del año previo.")
    st.caption(f"{len(res['sin_mapear'])} líneas del PDF no se clasificaron (ver pestaña 8); normalmente son detalles de cuentas que no afectan los indicadores.")
    dfv = pd.DataFrame(res["validaciones"], columns=["Validación", "Valor A", "Valor B", "Estado"])
    st.subheader("Validaciones contables (millones COP)")
    st.dataframe(dfv, width="stretch", hide_index=True)
    if (dfv["Estado"] == "REVISAR").any():
        st.error("Hay validaciones por revisar: contrasta con el PDF antes de continuar.")
    if hechos:
        st.subheader("Hechos identificados en las notas")
        st.dataframe(pd.DataFrame([{"Hecho": k, "Valor": v["valor"], "Fuente": v["nota"]} for k, v in hechos.items()]),
                     width="stretch", hide_index=True)

# ---------------- 4. Diagnóstico ----------------
with t_dia:
    cols = st.columns(3)
    for col, ag in zip(cols, AGENTES):
        v = hall["veredictos"][ag]
        with col:
            st.subheader(NOMBRES_AGENTES[ag])
            st.markdown(f"{ICONO[v['estado']]} **{v['titular']}**")
            st.caption(v["texto"])
    st.subheader("Plan de acción priorizado")
    for i, p in enumerate(hall["plan"], 1):
        quien = " · ".join(NOMBRES_AGENTES[a] for a in p["agentes"])
        imp = f" — impacto aprox. {mm(p['impacto_m'])}" if p["impacto_m"] else ""
        st.markdown(f"**{i}.** {p['accion']}{imp}  \n<small>{ICONO[p['severidad']]} {p['titulo']} · {quien}</small>", unsafe_allow_html=True)
    for ag in AGENTES:
        with st.expander(f"{NOMBRES_AGENTES[ag]} · {len(hall['hallazgos'][ag])} hallazgos", expanded=False):
            for h in hall["hallazgos"][ag]:
                st.markdown(f"{ICONO[h['severidad']]} **{h['titulo']}**")
                st.write(h["evidencia"])
                st.caption(f"Recomendación: {h['recomendacion']} · Fuentes: {', '.join(h['fuentes'])}")
            if ag == "cumplimiento":
                st.info("Análisis de apoyo generado por reglas e IA. No reemplaza la revisoría fiscal ni constituye dictamen.")
    st.caption(AVISO)

# ---------------- 5. Indicadores ----------------
with t_ind:
    grupos = []
    for m in calc["metricas"]:
        if m["grupo"] not in grupos:
            grupos.append(m["grupo"])
    for g in grupos:
        st.subheader(g)
        filas = [{"Indicador": m["nombre"], "Actual": fmt_valor(m["actual"], m["fmt"]), "Anterior": fmt_valor(m["anterior"], m["fmt"]),
                  "Referencia": fmt_valor(m["ref"], m["fmt"]) if m["ref"] is not None else "",
                  "Estado": ESTADO[m["estado"]] if m["ref"] is not None else m["nota"]}
                 for m in calc["metricas"] if m["grupo"] == g]
        st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)
    filas_csv = [{"Grupo": m["grupo"], "Indicador": m["nombre"], "Actual": m["actual"], "Anterior": m["anterior"],
                  "Referencia": m["ref"], "Estado": m["estado"]} for m in calc["metricas"]]
    st.download_button("⬇️ Descargar indicadores (.csv)", pd.DataFrame(filas_csv).to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"indicadores_{st.session_state.get('nombre', 'cliente')}.csv", mime="text/csv")
    st.subheader("Covenants")
    st.dataframe(pd.DataFrame([{"Covenant": c["nombre"], "Actual": fmt_valor(c["actual"], c["fmt"]), "Límite": fmt_valor(c["limite"], c["fmt"]),
                                "Resultado": "Sin dato" if c["cumple"] is None else ("✅ Cumple" if c["cumple"] else "🔴 INCUMPLE")}
                               for c in calc["covenants"]]), width="stretch", hide_index=True)
    es = calc["estres"]
    st.subheader("Prueba de estrés")
    st.caption(f"Ventas −{n(es['params']['caida'] * 100, 0)}%, tasa +{n(es['params']['tasa'] * 100, 1)} puntos, "
               f"+{n(es['params']['dias'], 0)} días de cartera.")
    st.dataframe(pd.DataFrame([
        {"Concepto": "Ventas anualizadas", "Base": n(es["ventas"][0], 0), "Estrés": n(es["ventas"][1], 0)},
        {"Concepto": "EBITDA anualizado", "Base": n(es["ebitda"][0], 0), "Estrés": n(es["ebitda"][1], 0)},
        {"Concepto": "Cobertura de intereses", "Base": fmt_valor(es["cobertura"][0], "x"), "Estrés": fmt_valor(es["cobertura"][1], "x")},
        {"Concepto": "Deuda neta ÷ EBITDA", "Base": fmt_valor(es["dn_ebitda"][0], "x"), "Estrés": fmt_valor(es["dn_ebitda"][1], "x")},
        {"Concepto": "Caja absorbida por cartera", "Base": "", "Estrés": n(es["caja_cartera"], 0)},
    ]), width="stretch", hide_index=True)

# ---------------- 6. Proyección ----------------
with t_pro:
    st.write("Proyección de caja a 12 meses calculada por código. Parte de tus cifras actuales; los supuestos son editables.")
    mm_ = calc["m"]
    c1, c2, c3, c4 = st.columns(4)
    g = c1.slider("Crecimiento anual de ventas (%)", -20, 30, 5) / 100
    dc = c2.number_input("Días de cartera", value=float(round(mm_["dias_cartera"]["actual"] or 0, 1)))
    di = c3.number_input("Días de inventario", value=float(round(mm_["dias_inv"]["actual"] or 0, 1)))
    dp = c4.number_input("Días de proveedores", value=float(round(mm_["dias_prov"]["actual"] or 0, 1)))
    proy = {e: proyectar(salida_ed, adic, e, crecimiento=g, dias_cartera=dc, dias_inv=di, dias_prov=dp) for e in ESCENARIOS}
    esc = st.radio("Escenario", ESCENARIOS, index=1, horizontal=True)
    sel = proy[esc]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Caja final ($M)", n(sel["caja_final"], 0))
    k2.metric("Caja mínima ($M)", n(sel["caja_min"], 0), f"mes {sel['mes_min']}")
    k3.metric("Caja de seguridad ($M)", n(sel["caja_seguridad"], 0))
    k4.metric("Ciclo de caja (días)", n(sel["ciclo_final"], 0))
    if sel["bajo_seguridad"]:
        st.warning("La caja mínima proyectada queda por debajo de la caja de seguridad (30 días de costos y gastos).")
    df = pd.DataFrame({e: proy[e]["caja"] for e in ESCENARIOS}, index=range(1, 13))
    df["Caja de seguridad"] = sel["caja_seguridad"]
    st.line_chart(df)
    st.caption("Modelo simplificado: ajusta los días de cartera, inventario y proveedores en 6 meses; costos fijos constantes; "
               "sin estacionalidad. No garantiza resultados futuros.")

# ---------------- 7. Agentes ----------------
with t_age:
    ag = st.radio("¿Con quién quieres hablar?", AGENTES, format_func=lambda a: NOMBRES_AGENTES[a], horizontal=True)
    historial = st.session_state["chat"][ag]
    for q, r, info in historial:
        with st.chat_message("user"):
            st.write(q)
        with st.chat_message("assistant"):
            st.write(r)
            if info["fuentes"]:
                st.caption("Fuentes: " + ", ".join(info["fuentes"]))
            for a in info["advertencias"]:
                st.caption("⚠️ " + a)
    pregunta = st.chat_input("Escribe tu pregunta")
    if pregunta:
        resp = consultar_agente(ag, pregunta, ctx, [(q, r) for q, r, _ in historial], usar_ia=usar_ia)
        historial.append((pregunta, resp["texto"], resp))
        st.rerun()
    st.caption(f"Modo: {'IA' if usar_ia and os.environ.get('ANTHROPIC_API_KEY') else 'reglas'} · {AVISO}")

# ---------------- 8. Notas y sin mapear ----------------
with t_not:
    temas = sorted({c for nt in notas for c in nt["categorias"]})
    filtro = st.multiselect("Filtrar notas por tema", temas)
    for nt in notas:
        if filtro and not set(filtro) & set(nt["categorias"]):
            continue
        with st.expander(f"Nota {nt['nota']} · {nt['titulo']} — {', '.join(nt['categorias']) or 'sin tema'}"):
            st.write(nt["texto"])
    st.subheader("Líneas del PDF sin mapear")
    st.caption("Suelen ser detalles de cuentas que no se usan en los indicadores (propiedades, intangibles, impuestos por pagar...). "
               "Revisa solo si alguna es relevante para el cliente.")
    if res["sin_mapear"]:
        st.dataframe(pd.DataFrame([{"Etiqueta": r["etiqueta"], "Valor 1": r["valores"][0], "Valor 2": r["valores"][1],
                                    "Sección": r["seccion"], "Grupo": r["grupo"], "Página": r["pagina"]} for r in res["sin_mapear"]]),
                     width="stretch", hide_index=True)
    else:
        st.success("Todas las líneas con cifras fueron mapeadas.")

# ---------------- Descarga ----------------
st.divider()
if st.button("Generar Excel de diagnóstico"):
    res["salida"] = salida_ed
    with tempfile.TemporaryDirectory() as carpeta:
        ruta_pl = PLANTILLA_DEFECTO
        if plantilla_subida is not None:
            ruta_pl = Path(carpeta) / "plantilla.xlsx"
            ruta_pl.write_bytes(plantilla_subida.getbuffer())
        ruta_out = Path(carpeta) / "diagnostico.xlsx"
        filas_adic = {fila: adic.get(k) for k, _, fila, _, _ in ADIC_SPEC}
        escribir_plantilla(res, notas, str(ruta_pl), str(ruta_out), adic_filas=filas_adic)
        st.session_state["xlsx"] = ruta_out.read_bytes()
if "xlsx" in st.session_state:
    st.download_button("⬇️ Descargar diagnóstico (.xlsx)", st.session_state["xlsx"],
                       file_name=f"diagnostico_{st.session_state.get('nombre', 'cliente')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
