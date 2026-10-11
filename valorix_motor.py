#!/usr/bin/env python3
"""
VALORIX360 · Motor de análisis (cálculo determinista)

Convierte las cifras ya validadas (salida del extractor, en millones de COP) en:
  - métricas e indicadores (básicos, capital de trabajo, DuPont, deuda, valor, riesgo, estrés)
  - hechos extraídos de las notas (covenants, contingencias, deterioros, partes relacionadas)
  - hallazgos por agente (contable, financiero, cumplimiento) con evidencia y recomendación
  - plan de acción priorizado
  - proyección de caja a 12 meses

Principio de diseño: TODAS las cifras salen de este módulo (código). Los agentes de IA solo
interpretan lo que este módulo calcula y deben citar la fuente. Ningún modelo calcula cifras.
"""
import re
import unicodedata

from valorix_extractor import parse_numero

# --------------------------------------------------------------------------------------
# Supuestos adicionales (los mismos de las filas 44 a 67 de la hoja Datos)
# --------------------------------------------------------------------------------------
# clave, etiqueta, fila en Datos, tipo (m = millones, pct = porcentaje, x = veces, n = número), valor por defecto
ADIC_SPEC = [
    ("fy_ing", "Ingresos del año completo anterior", 47, "m", None),
    ("fy_costo", "Costo de ventas del año completo anterior", 48, "m", None),
    ("fy_gop", "Gastos operativos (sin D&A) del año completo anterior", 49, "m", None),
    ("fy_da", "Depreciación y amortización del año completo anterior", 50, "m", None),
    ("fy_cfo", "Flujo de caja operativo del año completo anterior", 51, "m", None),
    ("fy_un", "Utilidad neta del año completo anterior", 52, "m", None),
    ("cov_endeud", "Endeudamiento máximo pactado (%)", 54, "pct", None),
    ("cov_dscr", "Cobertura mínima del servicio de la deuda (x)", 55, "x", None),
    ("cov_dn", "Deuda neta / EBITDA máximo (x)", 56, "x", None),
    ("nr_gasto", "Gastos no recurrentes (se suman al EBITDA)", 44, "m", None),
    ("nr_ingreso", "Ingresos no recurrentes (se restan del EBITDA)", 45, "m", None),
    ("venc1", "Vencimiento deuda año 1", 57, "m", None),
    ("venc2", "Vencimiento deuda año 2", 58, "m", None),
    ("venc3", "Vencimiento deuda año 3", 59, "m", None),
    ("venc4", "Vencimiento deuda año 4 o más", 60, "m", None),
    ("ke", "Costo del patrimonio, Ke (%)", 63, "pct", None),
    ("tasa_renta", "Tasa nominal del impuesto de renta (%)", 64, "pct", 0.35),
    ("est_caida", "Estrés: caída de ventas (%)", 65, "pct", 0.15),
    ("est_tasa", "Estrés: alza de la tasa de interés (puntos %)", 66, "pct", 0.03),
    ("est_dias", "Estrés: aumento de días de cartera", 67, "n", 15),
]
ADIC_DEFECTO = {k: v for k, _, _, _, v in ADIC_SPEC}

# Referencias orientativas por sector; reemplazan las generales por indicador. Validar con datos de mercado antes de uso comercial.
SECTORES = ("General", "Comercio", "Manufactura", "Servicios")
REFERENCIAS_SECTOR = {
    "Comercio": dict(razon_corriente=1.3, prueba_acida=0.6, margen_bruto=0.25, margen_ebitda=0.08, margen_neto=0.03,
                     rotacion_inv=8.0, dias_inv=45.0, dias_cartera=30.0, dias_prov=45.0, ciclo_caja=45.0, endeudamiento=0.65,
                     margen_seguridad=0.10),
    "Manufactura": dict(prueba_acida=0.8, margen_ebitda=0.12, margen_neto=0.06, rotacion_inv=5.0, dias_inv=75.0,
                        dias_cartera=50.0, dias_prov=50.0, ciclo_caja=75.0),
    "Servicios": dict(prueba_acida=1.2, margen_bruto=0.45, margen_ebitda=0.18, margen_neto=0.10, rotacion_inv=12.0,
                      dias_inv=15.0, dias_cartera=60.0, dias_prov=30.0, ciclo_caja=45.0, endeudamiento=0.55),
}


# --------------------------------------------------------------------------------------
# Formato en español (1.234,5)
# --------------------------------------------------------------------------------------
def n(x, dec=1):
    if x is None:
        return "n/d"
    s = f"{x:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def pc(x, dec=1):
    return "n/d" if x is None else n(x * 100, dec) + "%"


def mm(x):
    return "n/d" if x is None else "$" + n(x, 0) + " millones"


def xx(x, dec=2):
    return "n/d" if x is None else n(x, dec) + "x"


def _sa(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


# --------------------------------------------------------------------------------------
# Periodos
# --------------------------------------------------------------------------------------
def _g(out, k, i):
    v = (out.get(k) or [None, None])[i]
    return None if v is None else float(v)


def periodo(out, i):
    def z(k):
        v = _g(out, k, i)
        return 0.0 if v is None else v

    ac = z("efectivo") + z("cxc") + z("inventarios") + z("otros_ac")
    pcor = z("oblig_cp") + z("proveedores") + z("otros_pc")
    act, pas = ac + z("anc"), pcor + z("pnc")
    ub = z("ingresos") - z("costo")
    ebitda = ub - z("gastos_op")
    uo = ebitda - z("da")
    un = uo - z("gastos_fin") - z("impuestos")
    dias = z("dias") or 365.0
    k = 365.0 / dias
    return dict(ac=ac, pc=pcor, act=act, pas=pas, pat=z("patrimonio"), ing=z("ingresos"), costo=z("costo"),
                gop=z("gastos_op"), da=z("da"), gf=z("gastos_fin"), imp=z("impuestos"), ub=ub, ebitda=ebitda,
                uo=uo, un=un, dias=dias, k=k, cfo=z("cfo"), capex=z("capex"), fcl=z("cfo") - z("capex"),
                sd=z("servicio_deuda"), ef=z("efectivo"), cxc=z("cxc"), inv=z("inventarios"), prov=z("proveedores"),
                dcp=z("oblig_cp"), dlp=z("deuda_lp"), capital=_g(out, "capital", i),
                ventas_a=z("ingresos") * k, uo_a=uo * k, un_a=un * k)


def d(a, b):
    return None if (a is None or b is None or b == 0) else a / b


# --------------------------------------------------------------------------------------
# Cálculo principal
# --------------------------------------------------------------------------------------
def calcular(out, adic=None, sector="General"):
    """out: {clave: [actual, anterior]} en millones. adic: supuestos adicionales (ver ADIC_SPEC). sector: ver SECTORES."""
    A = dict(ADIC_DEFECTO)
    A.update({k: v for k, v in (adic or {}).items() if v is not None})
    refs_sector = REFERENCIAS_SECTOR.get(sector, {})
    p0, p1 = periodo(out, 0), periodo(out, 1)
    metricas = []

    def M(id_, grupo, nombre, a, p=None, ref=None, mejor=None, fmt="x", fuente="", nota=""):
        ref = refs_sector.get(id_, ref)
        estado = "n/d"
        if a is not None and ref is not None and mejor:
            estado = "Bien" if (a >= ref if mejor == "Mayor" else a <= ref) else "Revisar"
        metricas.append(dict(id=id_, grupo=grupo, nombre=nombre, actual=a, anterior=p, ref=ref, mejor_si=mejor,
                             estado=estado, fmt=fmt, fuente=fuente, nota=nota))

    def both(fn):
        return fn(p0), fn(p1)

    # ---- Liquidez
    a, p = both(lambda q: d(q["ac"], q["pc"])); M("razon_corriente", "Liquidez", "Razón corriente", a, p, 1.5, "Mayor", "x", "Balance")
    a, p = both(lambda q: d(q["ac"] - q["inv"], q["pc"])); M("prueba_acida", "Liquidez", "Prueba ácida", a, p, 1.0, "Mayor", "x", "Balance")
    a, p = both(lambda q: q["ac"] - q["pc"]); M("ctn", "Liquidez", "Capital de trabajo neto ($M)", a, p, 0.0, "Mayor", "m", "Balance")
    a, p = both(lambda q: d(q["ef"], q["pc"])); M("razon_efectivo", "Liquidez", "Razón de efectivo", a, p, 0.2, "Mayor", "x", "Balance")
    # ---- Flujo de caja
    a, p = both(lambda q: d(q["cfo"], q["un"])); M("calidad_utilidades", "Flujo de caja", "Calidad de utilidades", a, p, 1.0, "Mayor", "x", "Flujo de efectivo / Resultados")
    a, p = both(lambda q: q["fcl"]); M("fcl", "Flujo de caja", "Flujo de caja libre ($M)", a, p, 0.0, "Mayor", "m", "Flujo de efectivo")
    a, p = both(lambda q: d(q["cfo"], q["sd"])); M("dscr", "Flujo de caja", "Cobertura del servicio de deuda", a, p, 1.25, "Mayor", "x", "Flujo de efectivo")
    a, p = both(lambda q: d(q["ef"], (q["costo"] + q["gop"]) / q["dias"])); M("dias_caja", "Flujo de caja", "Días de caja", a, p, 30.0, "Mayor", "dias", "Balance / Resultados")
    # ---- Utilidades
    a, p = both(lambda q: d(q["ub"], q["ing"])); M("margen_bruto", "Utilidades", "Margen bruto", a, p, 0.30, "Mayor", "pct", "Resultados")
    a, p = both(lambda q: d(q["ebitda"], q["ing"])); M("margen_ebitda", "Utilidades", "Margen EBITDA", a, p, 0.15, "Mayor", "pct", "Resultados")
    a, p = both(lambda q: d(q["un"], q["ing"])); M("margen_neto", "Utilidades", "Margen neto", a, p, 0.08, "Mayor", "pct", "Resultados")
    a, p = both(lambda q: (d(q["un"], q["pat"]) or 0) * q["k"]); M("roe", "Utilidades", "ROE (anualizado)", a, p, 0.12, "Mayor", "pct", "Resultados / Balance")
    a, p = both(lambda q: (d(q["un"], q["act"]) or 0) * q["k"]); M("roa", "Utilidades", "ROA (anualizado)", a, p, 0.06, "Mayor", "pct", "Resultados / Balance")
    # ---- Inventarios y ciclo
    a, p = both(lambda q: (d(q["costo"], q["inv"]) or 0) * q["k"]); M("rotacion_inv", "Inventarios y ciclo", "Rotación de inventarios (anualizada)", a, p, 6.0, "Mayor", "x", "Balance / Resultados")
    di0, di1 = both(lambda q: (d(q["inv"], q["costo"]) or 0) * q["dias"]); M("dias_inv", "Inventarios y ciclo", "Días de inventario", di0, di1, 60.0, "Menor", "dias", "Balance / Resultados")
    dc0, dc1 = both(lambda q: (d(q["cxc"], q["ing"]) or 0) * q["dias"]); M("dias_cartera", "Inventarios y ciclo", "Días de cartera", dc0, dc1, 45.0, "Menor", "dias", "Balance / Resultados")
    dp0, dp1 = both(lambda q: (d(q["prov"], q["costo"]) or 0) * q["dias"]); M("dias_prov", "Inventarios y ciclo", "Días de proveedores", dp0, dp1, 45.0, "Mayor", "dias", "Balance / Resultados")
    M("ciclo_caja", "Inventarios y ciclo", "Ciclo de conversión de efectivo", di0 + dc0 - dp0, di1 + dc1 - dp1, 60.0, "Menor", "dias", "Balance / Resultados")
    # ---- Endeudamiento
    a, p = both(lambda q: d(q["pas"], q["act"])); M("endeudamiento", "Endeudamiento", "Endeudamiento total", a, p, 0.60, "Menor", "pct", "Balance")
    a, p = both(lambda q: d(q["uo"], q["gf"])); M("cobertura_intereses", "Endeudamiento", "Cobertura de intereses", a, p, 3.0, "Mayor", "x", "Resultados")

    # ---- Capital de trabajo (KTNO)
    kt0, kt1 = p0["cxc"] + p0["inv"] - p0["prov"], p1["cxc"] + p1["inv"] - p1["prov"]
    M("ktno", "Capital de trabajo (KTNO)", "KTNO = Cartera + Inventarios − Proveedores ($M)", kt0, kt1, fmt="m", fuente="Balance")
    pkt0, pkt1 = d(kt0, p0["ventas_a"]), d(kt1, p1["ventas_a"])
    M("pkt", "Capital de trabajo (KTNO)", "PKT = KTNO ÷ ventas anualizadas", pkt0, pkt1, fmt="pct", fuente="Balance / Resultados",
      nota="Centavos de caja que cada peso de ventas mantiene atrapados.")
    M("ktno_dias", "Capital de trabajo (KTNO)", "KTNO en días de ventas", (pkt0 or 0) * 365, (pkt1 or 0) * 365, fmt="dias")
    inc = d(kt0 - kt1, p0["ventas_a"] - p1["ventas_a"])
    M("caja_por_crecimiento", "Capital de trabajo (KTNO)", "Caja consumida por cada $1 de crecimiento de ventas", inc, None, fmt="x",
      nota="Si supera el PKT, crecer consume más caja que el promedio.")

    # ---- DuPont
    mn = lambda q: d(q["un"], q["ing"]) or 0
    rot = lambda q: d(q["ventas_a"], q["act"]) or 0
    apal = lambda q: d(q["act"], q["pat"]) or 0
    M("dupont_margen", "DuPont", "Margen neto", mn(p0), mn(p1), fmt="pct")
    M("dupont_rotacion", "DuPont", "Rotación de activos", rot(p0), rot(p1), fmt="x")
    M("dupont_apalancamiento", "DuPont", "Apalancamiento (activos ÷ patrimonio)", apal(p0), apal(p1), fmt="x")
    M("dupont_roe", "DuPont", "ROE = margen × rotación × apalancamiento", mn(p0) * rot(p0) * apal(p0), mn(p1) * rot(p1) * apal(p1), fmt="pct")

    # ---- EBITDA normalizado
    nr_g, nr_i = A.get("nr_gasto") or 0.0, A.get("nr_ingreso") or 0.0
    en0 = p0["ebitda"] + nr_g - nr_i
    M("ebitda_norm", "EBITDA", "EBITDA normalizado ($M)", en0, p1["ebitda"], fmt="m", fuente="Resultados + ajustes",
      nota="Suma gastos no recurrentes y resta ingresos únicos.")

    # ---- LTM
    fy = {k: A.get(f"fy_{k}") for k in ("ing", "costo", "gop", "da", "cfo", "un")}
    fy_ebitda = None if None in (fy["ing"], fy["costo"], fy["gop"]) else fy["ing"] - fy["costo"] - fy["gop"]
    anual = p0["dias"] >= 365

    def ltm(act_v, fy_v, prev_v):
        if anual:
            return act_v
        return None if fy_v is None else fy_v + act_v - prev_v

    ltm_ing = ltm(p0["ing"], fy["ing"], p1["ing"])
    ltm_ebitda = p0["ebitda"] if anual else (None if fy_ebitda is None else fy_ebitda + p0["ebitda"] - p1["ebitda"])
    ltm_cfo = ltm(p0["cfo"], fy["cfo"], p1["cfo"])
    ltm_un = ltm(p0["un"], fy["un"], p1["un"])
    M("ltm_ingresos", "Últimos 12 meses (LTM)", "Ingresos LTM ($M)", ltm_ing, fy["ing"], fmt="m", nota="Anterior = año completo anterior.")
    M("ltm_ebitda", "Últimos 12 meses (LTM)", "EBITDA LTM ($M)", ltm_ebitda, fy_ebitda, fmt="m")
    M("ltm_cfo", "Últimos 12 meses (LTM)", "Flujo operativo LTM ($M)", ltm_cfo, fy["cfo"], fmt="m")
    M("ltm_un", "Últimos 12 meses (LTM)", "Utilidad neta LTM ($M)", ltm_un, fy["un"], fmt="m")

    # ---- Deuda
    dt0, dt1 = p0["dcp"] + p0["dlp"], p1["dcp"] + p1["dlp"]
    dn0, dn1 = dt0 - p0["ef"], dt1 - p1["ef"]
    dne0, dne1 = d(dn0, ltm_ebitda), d(dn1, fy_ebitda)
    M("deuda_total", "Deuda", "Deuda financiera total ($M)", dt0, dt1, fmt="m", fuente="Balance")
    M("deuda_neta", "Deuda", "Deuda neta ($M)", dn0, dn1, fmt="m")
    M("deuda_neta_ebitda", "Deuda", "Deuda neta ÷ EBITDA (LTM)", dne0, dne1, fmt="x",
      nota="Años de EBITDA para pagar la deuda neta.")
    M("deuda_total_ebitda", "Deuda", "Deuda total ÷ EBITDA (LTM)", d(dt0, ltm_ebitda), d(dt1, fy_ebitda), fmt="x")
    costo_deuda = d(p0["gf"] * p0["k"], (dt0 + dt1) / 2)
    M("costo_deuda", "Deuda", "Costo promedio de la deuda (anualizado)", costo_deuda, None, fmt="pct")
    M("pct_deuda_cp", "Deuda", "% de la deuda en corto plazo", d(p0["dcp"], dt0), d(p1["dcp"], dt1), fmt="pct")

    # ---- Covenants
    covenants = []

    def cov(nombre, actual, limite, tipo, fmt):
        if limite is None or actual is None:
            covenants.append(dict(nombre=nombre, actual=actual, limite=limite, tipo=tipo, cumple=None, holgura=None, fmt=fmt))
            return
        ok = actual <= limite if tipo == "max" else actual >= limite
        h = (limite - actual) if tipo == "max" else (actual - limite)
        covenants.append(dict(nombre=nombre, actual=actual, limite=limite, tipo=tipo, cumple=ok, holgura=h, fmt=fmt))

    cov("Endeudamiento total (máximo)", d(p0["pas"], p0["act"]), A.get("cov_endeud"), "max", "pct")
    cov("Deuda neta ÷ EBITDA (máximo)", dne0, A.get("cov_dn"), "max", "x")
    cov("Cobertura del servicio de la deuda (mínimo)", d(p0["cfo"], p0["sd"]), A.get("cov_dscr"), "min", "x")

    venc = [A.get(f"venc{i}") for i in (1, 2, 3, 4)]
    venc_ok = any(v is not None for v in venc)
    venc_total = sum(v or 0 for v in venc)
    vencimientos = dict(montos=[v or 0 for v in venc], total=venc_total, hay_datos=venc_ok,
                        cuadra=abs(venc_total - dt0) < 1 if venc_ok else None,
                        pct_ano1=d(venc[0] or 0, venc_total) if venc_ok else None)

    # ---- Valor: ROIC, WACC, EVA
    tasa_ef = d(p0["imp"], p0["uo"] - p0["gf"])
    nopat = p0["uo_a"] * (1 - (tasa_ef or 0))
    cap_inv = p0["pat"] + dt0 - p0["ef"]
    roic = d(nopat, cap_inv)
    pd_ = d(dt0, dt0 + p0["pat"])
    ke = A.get("ke")
    wacc = None if (ke is None or costo_deuda is None or pd_ is None) else (1 - pd_) * ke + pd_ * costo_deuda * (1 - (tasa_ef or 0))
    spread = None if (wacc is None or roic is None) else roic - wacc
    eva = None if spread is None else spread * cap_inv
    M("tasa_efectiva", "Valor", "Tasa efectiva de impuestos", tasa_ef, d(p1["imp"], p1["uo"] - p1["gf"]), fmt="pct")
    M("nopat", "Valor", "NOPAT anualizado ($M)", nopat, None, fmt="m")
    M("capital_invertido", "Valor", "Capital invertido ($M)", cap_inv, p1["pat"] + dt1 - p1["ef"], fmt="m")
    M("roic", "Valor", "ROIC", roic, None, fmt="pct")
    M("wacc", "Valor", "WACC", wacc, None, fmt="pct", nota="Requiere el costo del patrimonio (Ke).")
    M("spread", "Valor", "Spread ROIC − WACC", spread, None, fmt="pct")
    M("eva", "Valor", "EVA anualizado ($M)", eva, None, fmt="m")

    # ---- Altman Z'' (mercados emergentes)
    def altman(q):
        if q["capital"] is None or q["act"] == 0 or q["pas"] == 0:
            return None, None
        x1 = (q["ac"] - q["pc"]) / q["act"]
        x2 = (q["pat"] - q["capital"]) / q["act"]
        x3 = q["uo_a"] / q["act"]
        x4 = q["pat"] / q["pas"]
        return 3.25 + 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4, (x1, x2, x3, x4)

    z0, z1 = altman(p0)[0], altman(p1)[0]
    zona = None if z0 is None else ("Zona segura" if z0 > 5.85 else "Zona gris" if z0 >= 4.15 else "Zona de riesgo")
    M("altman_z", "Riesgo", "Altman Z'' (mercados emergentes)", z0, z1, fmt="num", nota=zona or "Requiere el capital social.")

    # ---- Punto de equilibrio
    mc = d(p0["ing"] - p0["costo"], p0["ing"])
    cf = (p0["gop"] + p0["da"] + p0["gf"]) * p0["k"]
    pe = d(cf, mc)
    ms = d(p0["ventas_a"] - pe, p0["ventas_a"]) if pe is not None else None
    gao = d(p0["ventas_a"] * mc, p0["uo_a"]) if mc is not None else None
    M("margen_contribucion", "Punto de equilibrio", "Margen de contribución", mc, None, fmt="pct")
    M("ventas_equilibrio", "Punto de equilibrio", "Ventas de equilibrio anualizadas ($M)", pe, None, fmt="m",
      nota="Supone costo de ventas variable; gastos operativos, D&A y financieros fijos.")
    M("margen_seguridad", "Punto de equilibrio", "Margen de seguridad", ms, None, 0.15, "Mayor", "pct")
    M("gao", "Punto de equilibrio", "Apalancamiento operativo", gao, None, fmt="x")

    # ---- Calidad de utilidades
    M("accruals", "Calidad de utilidades", "Accruals (utilidad neta − flujo operativo) ÷ activos", d(p0["un"] - p0["cfo"], p0["act"]),
      d(p1["un"] - p1["cfo"], p1["act"]), 0.03, "Menor", "pct")
    M("fcl_sobre_un", "Calidad de utilidades", "Flujo de caja libre ÷ utilidad neta", d(p0["fcl"], p0["un"]), d(p1["fcl"], p1["un"]), fmt="x")
    M("tasa_dif", "Calidad de utilidades", "Tasa efectiva − tasa nominal de renta", None if tasa_ef is None else tasa_ef - A["tasa_renta"], None, fmt="pct")

    # ---- Estrés
    vs = p0["ventas_a"] * (1 - A["est_caida"])
    e_base = (p0["ing"] - p0["costo"] - p0["gop"]) * p0["k"]
    e_est = vs * (mc or 0) - p0["gop"] * p0["k"]
    uo_e = e_est - p0["da"] * p0["k"]
    gf_b = p0["gf"] * p0["k"]
    gf_e = gf_b + dt0 * A["est_tasa"]
    estres = dict(
        ventas=(p0["ventas_a"], vs), ebitda=(e_base, e_est), uo=(p0["uo_a"], uo_e), gf=(gf_b, gf_e),
        cobertura=(d(p0["uo_a"], gf_b), d(uo_e, gf_e)),
        dn_ebitda=(d(dn0, e_base), d(dn0, e_est) if e_est > 0 else None),
        caja_cartera=vs / 365 * A["est_dias"], params=dict(caida=A["est_caida"], tasa=A["est_tasa"], dias=A["est_dias"]))
    lim = A.get("cov_dn")
    estres["covenant_dn"] = (None if lim is None or estres["dn_ebitda"][1] is None else
                             ("Cumple" if estres["dn_ebitda"][1] <= lim else "INCUMPLE"))

    return dict(adic=A, sector=sector, p0=p0, p1=p1, metricas=metricas, m={x["id"]: x for x in metricas}, covenants=covenants,
                vencimientos=vencimientos, estres=estres, zona_altman=zona, ltm=dict(ebitda=ltm_ebitda, ing=ltm_ing),
                deuda=dict(total=dt0, neta=dn0), tasa_efectiva=tasa_ef, wacc=wacc, roic=roic, eva=eva, cap_inv=cap_inv)


# --------------------------------------------------------------------------------------
# Hechos de las notas (reglas). Para notas muy distintas conviene reforzar con extracción por IA.
# --------------------------------------------------------------------------------------
def _dinero(num, unidad, factor_doc):
    v = parse_numero(num)
    if v is None:
        return None
    u = (unidad or "").lower()
    if "millon" in u:
        return v
    if "mil" in u:
        return v / 1e3
    return v * (factor_doc if factor_doc else 1.0)


MONEY = r"\$?\s*([\d][\d.,]*)\s*(?:\((miles|millones)(?: de pesos)?\)|(miles|millones)(?: de pesos)?)?"


def extraer_hechos(notas, factor_doc=1e-3):
    """Devuelve {clave: {valor, nota, texto}} con lo que se pueda identificar por reglas."""
    hechos = {}

    def reg(clave, valor, nota, extra=None):
        if clave not in hechos and valor is not None:
            hechos[clave] = dict(valor=valor, nota=nota, **(extra or {}))

    for nt in notas:
        t = _sa(nt["titulo"] + ". " + nt["texto"])
        etiqueta = f"Nota {nt['nota']}" if nt["nota"] else "Notas"
        m = re.search(r"(\d{1,3}(?:[.,]\d+)?)\s*%[^.]{0,80}?(?:supera|excede|mayor(?:es)? a|mas de)\s*(?:los\s*)?90", t)
        if m:
            reg("cartera_vencida_pct", parse_numero(m.group(1)), etiqueta)
        m = re.search(r"deterioro[^.]{0,80}?(?:asciende a|es de|por|de)\s*" + MONEY, t)
        if m and ("cartera" in t or "deudores" in t):
            reg("deterioro_cartera", _dinero(m.group(1), m.group(2) or m.group(3), factor_doc), etiqueta)
        m = re.search(r"(?:deterioro|obsolescencia)[^.]{0,100}?por\s*" + MONEY, t)
        if m and "inventario" in t:
            reg("deterioro_inventario", _dinero(m.group(1), m.group(2) or m.group(3), factor_doc), etiqueta)
        m = re.search(r"endeudamiento\s+maximo\s*(?:de|del)?\s*(\d{1,3}(?:[.,]\d+)?)\s*%", t)
        if m:
            reg("cov_endeud", parse_numero(m.group(1)) / 100, etiqueta)
        m = re.search(r"(?:proceso|litigio|demanda)[^.]{0,80}?por\s*" + MONEY + r"[^.]{0,60}?(probable|posible|remota)", t)
        if m:
            reg("contingencia", _dinero(m.group(1), m.group(2) or m.group(3), factor_doc), etiqueta,
                dict(prob=m.group(4), tipo="proceso laboral" if "laboral" in t else "proceso judicial"))
        m = re.search(r"prestamos?\s+de\s+accionistas\s+por\s*" + MONEY, t)
        if m:
            reg("prestamos_accionistas", _dinero(m.group(1), m.group(2) or m.group(3), factor_doc), etiqueta)
        m = re.search(r"(ibr|dtf|ipc)\s*\+\s*(\d+(?:[.,]\d+)?)\s*%", t)
        if m:
            reg("tasa_credito", f"{m.group(1).upper()} + {m.group(2)}%", etiqueta)
        m = re.search(r"garantia\s+(prendaria|hipotecaria|personal|fiduciaria)", t)
        if m:
            reg("garantia", m.group(1), etiqueta)
    return hechos


# --------------------------------------------------------------------------------------
# Hallazgos por agente
# --------------------------------------------------------------------------------------
SEV = {"ok": 0, "atencion": 1, "riesgo": 2}
NOMBRES = {"contable": "Agente contable", "financiero": "Agente financiero", "cumplimiento": "Agente de cumplimiento y riesgos"}


def generar_hallazgos(res, hechos=None, validaciones=None, out=None):
    hechos, validaciones = hechos or {}, validaciones or []
    M, p0 = res["m"], res["p0"]
    H = {"contable": [], "financiero": [], "cumplimiento": []}

    def add(ag, titulo, sev, evidencia, recom, fuentes, impacto=None):
        H[ag].append(dict(titulo=titulo, severidad=sev, evidencia=evidencia, recomendacion=recom, fuentes=fuentes, impacto_m=impacto))

    # ===== CONTABLE
    if validaciones:
        malas = [v for v in validaciones if v[3] == "REVISAR"]
        if not malas:
            add("contable", "Información consistente", "ok", f"Los {len(validaciones)} cuadres contables cierran.",
                "Mantener estos controles en cada cierre.", ["Validaciones contables"])
        else:
            add("contable", "Cuadres contables por revisar", "riesgo",
                f"{len(malas)} de {len(validaciones)} validaciones no cierran: " + "; ".join(v[0] for v in malas) + ".",
                "Contrastar con el PDF y corregir antes de usar el diagnóstico.", ["Validaciones contables"])
    cxc = p0["cxc"]
    pct, det = hechos.get("cartera_vencida_pct"), hechos.get("deterioro_cartera")
    vencida = None
    if pct and det:
        vencida = pct["valor"] / 100 * cxc
        cob = det["valor"] / vencida if vencida else None
        sev = "ok" if (cob is not None and cob >= 1) else "atencion"
        add("contable", "Deterioro de cartera", sev,
            f"{pct['nota']}: el {n(pct['valor'], 0)}% de la cartera supera 90 días (≈{mm(vencida)}) y el deterioro acumulado es de "
            f"{mm(det['valor'])}" + (f", que cubre el {n(cob * 100, 0)}% de esa cartera." if cob is not None else "."),
            "Verificar si el deterioro cubre la cartera vencida y documentar el criterio." if sev != "ok" else "Mantener el criterio y revisarlo en cada cierre.",
            [pct["nota"], "Balance: cuentas por cobrar"], None)
    ri = M["rotacion_inv"]
    if ri["estado"] == "Revisar":
        det_i = hechos.get("deterioro_inventario")
        extra = f" {det_i['nota']}: deterioro por obsolescencia de {mm(det_i['valor'])}." if det_i else ""
        add("contable", "Obsolescencia de inventarios", "atencion",
            f"La rotación anualizada es de {xx(ri['actual'], 1)} frente a una referencia de {xx(ri['ref'], 0)}.{extra}",
            "Clasificar el inventario por antigüedad y evaluar si el deterioro registrado es suficiente.",
            [det_i["nota"] if det_i else "Balance: inventarios", "indicador: rotacion_inv"])
    ac = M["accruals"]
    if ac["actual"] is not None and ac["estado"] == "Revisar":
        add("contable", "La utilidad contable supera la caja", "atencion",
            f"La utilidad neta supera al flujo operativo en {pc(ac['actual'])} de los activos (referencia: hasta {pc(ac['ref'])}).",
            "Revisar partidas devengadas que no se han recaudado: cartera, inventarios y otros activos.", ["indicador: accruals"])

    # ===== FINANCIERO
    cu = M["calidad_utilidades"]
    if cu["actual"] is not None and cu["estado"] == "Revisar":
        sev = "riesgo" if cu["actual"] < 0.5 else "atencion"
        add("financiero", "La utilidad no se convierte en caja", sev,
            f"Solo {xx(cu['actual'])} de la utilidad neta llega como flujo operativo (antes: {xx(cu['anterior'])}). Cartera e inventarios absorben el efectivo.",
            "Acelerar el recaudo y reducir el capital inmovilizado en inventario.", ["indicador: calidad_utilidades"])
    di = M["dias_inv"]
    palancas = []
    if di["actual"] is not None and di["estado"] == "Revisar" and p0["costo"]:
        liberar = (di["actual"] - di["ref"]) * p0["costo"] / p0["dias"]
        palancas.append(dict(nombre="Llevar los días de inventario a la referencia", monto_m=liberar,
                             detalle=f"de {n(di['actual'], 0)} a {n(di['ref'], 0)} días", fuente="indicador: dias_inv"))
        add("financiero", "Inventario lento", "atencion",
            f"{n(di['actual'], 0)} días de inventario frente a una referencia de {n(di['ref'], 0)}; llevarlo a la referencia liberaría cerca de {mm(liberar)}.",
            "Liquidar referencias de baja salida y comprar según la demanda proyectada.", ["indicador: dias_inv"], liberar)
    if vencida:
        palancas.append(dict(nombre="Recaudar la cartera vencida a más de 90 días", monto_m=vencida,
                             detalle=f"{n(pct['valor'], 0)}% de la cartera", fuente=pct["nota"]))
    else:
        dc = M["dias_cartera"]
        if dc["actual"] is not None and dc["estado"] == "Revisar":
            lib = (dc["actual"] - dc["ref"]) * p0["ing"] / p0["dias"]
            palancas.append(dict(nombre="Llevar los días de cartera a la referencia", monto_m=lib, detalle="", fuente="indicador: dias_cartera"))
    pa = M["prueba_acida"]
    if pa["actual"] is not None and pa["estado"] == "Revisar":
        add("financiero", "Liquidez atada al inventario", "atencion",
            f"La prueba ácida es {xx(pa['actual'])} frente a {xx(pa['ref'], 1)}: sin vender inventario, no alcanza para cubrir el pasivo corriente.",
            "Priorizar la rotación del inventario y renegociar plazos de corto plazo.", ["indicador: prueba_acida"])
    cc = M["ciclo_caja"]
    if cc["actual"] is not None and cc["estado"] == "Revisar":
        add("financiero", "Ciclo de caja largo", "atencion",
            f"El ciclo de conversión de efectivo es de {n(cc['actual'], 0)} días frente a una referencia de {n(cc['ref'], 0)}.",
            "Reducir los días de inventario y cartera antes de alargar proveedores.", ["indicador: ciclo_caja"])
    mnet, cob = M["margen_neto"], M["cobertura_intereses"]
    if mnet["estado"] == "Bien" and cob["estado"] == "Bien":
        add("financiero", "Rentabilidad y deuda sanas", "ok",
            f"Margen neto de {pc(mnet['actual'])} y cobertura de intereses de {xx(cob['actual'], 1)}: hay espacio para financiar la mejora de caja.",
            "Usar parte de esa holgura para sostener el capital de trabajo.", ["indicador: margen_neto", "indicador: cobertura_intereses"])
    sp = M["spread"]
    if sp["actual"] is not None:
        add("financiero", "Creación de valor", "ok" if sp["actual"] > 0 else "riesgo",
            f"ROIC de {pc(M['roic']['actual'])} frente a un WACC de {pc(M['wacc']['actual'])}: spread de {pc(sp['actual'])}; EVA anualizado de {mm(M['eva']['actual'])}.",
            "Mantener el retorno sobre el capital por encima de su costo." if sp["actual"] > 0 else "Revisar inversiones y capital inmovilizado que no remuneran su costo.",
            ["indicador: roic", "indicador: wacc"])
    ms = M["margen_seguridad"]
    if ms["actual"] is not None:
        sev = "riesgo" if ms["actual"] < 0 else "atencion" if ms["estado"] == "Revisar" else "ok"
        add("financiero", "Margen de seguridad de las ventas", sev,
            f"Las ventas pueden caer {pc(ms['actual'], 0)} antes de entrar en pérdida (equilibrio en {mm(M['ventas_equilibrio']['actual'])} anualizados).",
            "Vigilar los costos fijos si el margen de seguridad es bajo." if sev != "ok" else "Mantener el control de costos fijos.", ["indicador: margen_seguridad"])
    es = res["estres"]
    ce = es["cobertura"][1]
    if ce is not None:
        sev = "riesgo" if ce < 1 else "atencion" if ce < 1.5 else "ok"
        add("financiero", "Resistencia a un escenario adverso", sev,
            f"Con ventas {pc(-es['params']['caida'], 0)} y tasas +{n(es['params']['tasa'] * 100, 0)} puntos, la cobertura de intereses pasa de {xx(es['cobertura'][0], 1)} a {xx(ce, 1)} "
            f"y la cartera absorbería {mm(es['caja_cartera'])} adicionales.",
            "Preparar un plan de contingencia de caja y revisar costos fijos." if sev != "ok" else "El negocio resiste el escenario planteado.", ["Prueba de estrés"])

    # ===== CUMPLIMIENTO Y RIESGOS
    fuente_cov = hechos.get("cov_endeud", {}).get("nota", "Supuestos del usuario")
    hay_cov = False
    for cv in res["covenants"]:
        if cv["cumple"] is None:
            continue
        hay_cov = True
        f = (lambda v: pc(v)) if cv["fmt"] == "pct" else (lambda v: xx(v))
        sev = "riesgo" if not cv["cumple"] else ("atencion" if cv["limite"] and cv["holgura"] / abs(cv["limite"]) < 0.15 else "ok")
        sentido = "máximo" if cv["tipo"] == "max" else "mínimo"
        hol = (n(cv["holgura"] * 100, 1) + " puntos") if cv["fmt"] == "pct" else xx(cv["holgura"])
        add("cumplimiento", cv["nombre"].replace(" (máximo)", "").replace(" (mínimo)", ""), sev,
            f"Actual {f(cv['actual'])} frente a un {sentido} pactado de {f(cv['limite'])} ({fuente_cov}): " +
            (f"holgura de {hol}." if cv["cumple"] else "INCUMPLE el límite pactado."),
            "Monitorear cada trimestre y evitar nueva deuda sin proyección." if cv["cumple"] else "Gestionar de inmediato con el acreedor una dispensa o un plan de ajuste.",
            [fuente_cov, "Balance"])
    if not hay_cov:
        add("cumplimiento", "Covenants sin registrar", "atencion",
            "No hay covenants ingresados, por lo que no se puede probar el cumplimiento.",
            "Registrar los límites pactados en la nota de obligaciones financieras.", ["Supuestos"])
    ct = hechos.get("contingencia")
    if ct:
        patr = p0["pat"]
        add("cumplimiento", "Contingencia legal", "atencion" if ct.get("prob") == "probable" else "ok",
            f"{ct['nota']}: {ct.get('tipo', 'proceso')} calificado como {ct.get('prob', 'n/d')} por {mm(ct['valor'])} ({pc(ct['valor'] / patr) if patr else 'n/d'} del patrimonio).",
            "Verificar que esté provisionado y debidamente revelado.", [ct["nota"]], ct["valor"])
    pr = hechos.get("prestamos_accionistas")
    if pr:
        add("cumplimiento", "Partes relacionadas", "atencion", f"{pr['nota']}: préstamos de accionistas por {mm(pr['valor'])}.",
            "Confirmar condiciones de mercado y soporte documental.", [pr["nota"]])
    v = res["vencimientos"]
    if v["hay_datos"] and v["pct_ano1"] is not None:
        sev = "atencion" if v["pct_ano1"] > 0.5 else "ok"
        add("cumplimiento", "Perfil de vencimientos de la deuda", sev,
            f"El {pc(v['pct_ano1'], 0)} de la deuda vence en el primer año." + ("" if v["cuadra"] else " La tabla de vencimientos no cuadra con la deuda total."),
            "Anticipar la refinanciación." if sev != "ok" else "El perfil de vencimientos es manejable.", ["Nota de obligaciones financieras"])
    zona = res["zona_altman"]
    if zona:
        sev = "ok" if zona == "Zona segura" else "atencion" if zona == "Zona gris" else "riesgo"
        add("cumplimiento", "Riesgo de quiebra (Altman Z'')", sev,
            f"Z'' de {n(M['altman_z']['actual'], 2)}: {zona.lower()} (referencia académica para mercados emergentes).",
            "Usar como señal de alerta, no como sentencia.", ["indicador: altman_z"])
    te = M["tasa_dif"]["actual"]
    if te is not None and abs(te) > 0.05:
        add("cumplimiento", "Tasa efectiva de impuestos", "atencion",
            f"La tasa efectiva ({pc(res['tasa_efectiva'])}) difiere {n(abs(te) * 100, 1)} puntos de la nominal ({pc(res['adic']['tasa_renta'])}).",
            "Revisar en las notas de impuestos descuentos, diferidos o pérdidas fiscales.", ["indicador: tasa_efectiva"])

    # ---- veredictos
    def veredicto(ag):
        fs = sorted(H[ag], key=lambda x: -SEV[x["severidad"]])
        if not fs:
            return dict(estado="ok", titular="Sin hallazgos", texto="No hay hallazgos relevantes con la información cargada.")
        peor = fs[0]
        return dict(estado=peor["severidad"], titular=peor["titulo"] if peor["severidad"] != "ok" else "Sin alertas",
                    texto=" ".join(x["evidencia"] for x in fs[:2]))

    plan = []
    for ag, fs in H.items():
        for f in fs:
            if f["severidad"] != "ok":
                plan.append(dict(accion=f["recomendacion"], agentes=[ag], severidad=f["severidad"], impacto_m=f["impacto_m"], titulo=f["titulo"]))
    plan.sort(key=lambda x: (-SEV[x["severidad"]], -(x["impacto_m"] or 0)))
    return dict(hallazgos=H, veredictos={ag: veredicto(ag) for ag in H}, plan=plan[:8], palancas=sorted(palancas, key=lambda x: -x["monto_m"]))


# --------------------------------------------------------------------------------------
# Proyección de caja a 12 meses
# --------------------------------------------------------------------------------------
ESCENARIOS = ("Conservador", "Base", "Optimista")


def proyectar(out, adic=None, escenario="Base", crecimiento=0.0, meses=12, meses_ajuste=6, dias_caja_min=30,
              dias_cartera=None, dias_inv=None, dias_prov=None, margen_bruto=None):
    A = dict(ADIC_DEFECTO)
    A.update({k: v for k, v in (adic or {}).items() if v is not None})
    p = periodo(out, 0)
    va = p["ventas_a"]
    mb0 = d(p["ing"] - p["costo"], p["ing"]) or 0
    dc0 = (d(p["cxc"], va) or 0) * 365
    di0 = (d(p["inv"], p["costo"] * p["k"]) or 0) * 365
    dp0 = (d(p["prov"], p["costo"] * p["k"]) or 0) * 365
    dc_o = dias_cartera if dias_cartera is not None else dc0
    di_o = dias_inv if dias_inv is not None else di0
    dp_o = dias_prov if dias_prov is not None else dp0
    mb = margen_bruto if margen_bruto is not None else mb0
    g = crecimiento
    if escenario == "Conservador":
        g, dc_o, di_o, mb = g - 0.05, dc_o + 10, di_o + 10, mb - 0.01
    elif escenario == "Optimista":
        g, dc_o, di_o = g + 0.03, min(dc_o, 45.0), min(di_o, 60.0)

    gop_a, da_a, gf_a, capex_a = p["gop"] * p["k"], p["da"] * p["k"], p["gf"] * p["k"], p["capex"] * p["k"]
    capital_a = max(0.0, p["sd"] * p["k"] - gf_a)
    caja, ktno_prev = p["ef"], p["cxc"] + p["inv"] - p["prov"]
    serie, flujos = [], []
    for m in range(1, meses + 1):
        f = (1 + g) ** (m / 12)
        ventas_m = va / 12 * f
        costo_m = ventas_m * (1 - mb)
        ebitda_m = ventas_m - costo_m - gop_a / 12
        uai = ebitda_m - da_a / 12 - gf_a / 12
        imp = max(0.0, uai) * A["tasa_renta"]
        w = min(m / meses_ajuste, 1.0)
        dc, di, dp = dc0 + (dc_o - dc0) * w, di0 + (di_o - di0) * w, dp0 + (dp_o - dp0) * w
        vr, cr = ventas_m * 12, costo_m * 12
        ktno = vr / 365 * dc + cr / 365 * di - cr / 365 * dp
        flujo = ebitda_m - imp - gf_a / 12 - capex_a / 12 - capital_a / 12 - (ktno - ktno_prev)
        ktno_prev = ktno
        caja += flujo
        flujos.append(flujo)
        serie.append(caja)
    seguridad = dias_caja_min * (p["costo"] + p["gop"]) * p["k"] / 365
    imin = min(range(len(serie)), key=lambda i: serie[i])
    return dict(escenario=escenario, caja=serie, flujo=flujos, caja_final=serie[-1], caja_min=serie[imin], mes_min=imin + 1,
                caja_seguridad=seguridad, bajo_seguridad=serie[imin] < seguridad,
                ciclo_final=dc_o + di_o - dp_o, supuestos=dict(crecimiento=g, dias_cartera=dc_o, dias_inv=di_o, dias_prov=dp_o, margen_bruto=mb))


# --------------------------------------------------------------------------------------
# Formato de métricas para mostrar en pantalla
# --------------------------------------------------------------------------------------
def fmt_valor(v, fmt):
    if v is None:
        return "n/d"
    return {"x": lambda: xx(v), "pct": lambda: pc(v), "m": lambda: n(v, 0), "dias": lambda: n(v, 1) + " días", "num": lambda: n(v, 2)}.get(fmt, lambda: n(v, 2))()
