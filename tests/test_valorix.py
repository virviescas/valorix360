"""Pruebas del motor, el extractor y la verificación de cifras de los agentes."""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from valorix_agentes import construir_contexto, numeros, verificar_cifras  # noqa: E402
from valorix_extractor import consolidar, extraer, segmentar_notas  # noqa: E402
from valorix_motor import (ADIC_SPEC, ESCENARIOS, calcular, extraer_hechos, generar_hallazgos, n, pc,  # noqa: E402
                           periodo, proyectar)

PDF = RAIZ / "ejemplos" / "ejemplo_estados_financieros.pdf"


@pytest.fixture(scope="module")
def caso():
    res = extraer(str(PDF))
    consolidar(res)
    notas = segmentar_notas(res["notas_lineas"])
    adic = {k: d for k, _, _, _, d in ADIC_SPEC}
    hechos = extraer_hechos(notas, 1e-3)
    calc = calcular(res["salida"], adic)
    hall = generar_hallazgos(calc, hechos, res["validaciones"])
    return dict(res=res, notas=notas, adic=adic, hechos=hechos, calc=calc, hall=hall)


# ---------- Extractor ----------
def test_extractor_cuadres_contables(caso):
    malas = [v for v in caso["res"]["validaciones"] if v[3] == "REVISAR"]
    assert not malas
    assert len(caso["res"]["validaciones"]) >= 8


def test_extractor_periodos_y_dias(caso):
    assert caso["res"]["years"][:2] == [2026, 2025]
    assert caso["res"]["salida"]["dias"][0] == 181


# ---------- Motor ----------
def test_razon_corriente_coincide_con_balance(caso):
    p = periodo(caso["res"]["salida"], 0)
    assert caso["calc"]["m"]["razon_corriente"]["actual"] == pytest.approx(p["ac"] / p["pc"])


def test_ebitda_y_utilidad_neta_son_consistentes(caso):
    p = periodo(caso["res"]["salida"], 0)
    assert p["ebitda"] == pytest.approx(p["ing"] - p["costo"] - p["gop"])
    assert p["un"] == pytest.approx(p["ebitda"] - p["da"] - p["gf"] - p["imp"])


def test_ciclo_de_caja_es_inventario_mas_cartera_menos_proveedores(caso):
    m = caso["calc"]["m"]
    esperado = m["dias_inv"]["actual"] + m["dias_cartera"]["actual"] - m["dias_prov"]["actual"]
    assert m["ciclo_caja"]["actual"] == pytest.approx(esperado)


def test_covenant_con_limite_cero_no_falla(caso):
    adic = dict(caso["adic"], cov_endeud=0.0)
    calc = calcular(caso["res"]["salida"], adic)
    generar_hallazgos(calc, caso["hechos"], caso["res"]["validaciones"])


def test_covenant_incumplido_se_marca_riesgo(caso):
    adic = dict(caso["adic"], cov_endeud=0.01)
    calc = calcular(caso["res"]["salida"], adic)
    hall = generar_hallazgos(calc, caso["hechos"], caso["res"]["validaciones"])
    assert any(h["severidad"] == "riesgo" for h in hall["hallazgos"]["cumplimiento"])


def test_cartera_en_cero_con_notas_no_falla(caso):
    salida = {k: list(v) for k, v in caso["res"]["salida"].items()}
    salida["cxc"] = [0.0, 0.0]
    calc = calcular(salida, caso["adic"])
    generar_hallazgos(calc, caso["hechos"], caso["res"]["validaciones"])


def test_estres_reduce_ventas_y_ebitda(caso):
    es = caso["calc"]["estres"]
    assert es["ventas"][1] < es["ventas"][0]
    assert es["ebitda"][1] < es["ebitda"][0]


# ---------- Proyección ----------
def test_proyeccion_tiene_12_meses_y_escenarios_ordenados(caso):
    proy = {e: proyectar(caso["res"]["salida"], caso["adic"], e) for e in ESCENARIOS}
    assert all(len(p["caja"]) == 12 for p in proy.values())
    assert proy["Conservador"]["caja_final"] <= proy["Base"]["caja_final"] <= proy["Optimista"]["caja_final"]


def test_proyeccion_caja_final_es_ultimo_mes(caso):
    p = proyectar(caso["res"]["salida"], caso["adic"], "Base")
    assert p["caja_final"] == p["caja"][-1]
    assert p["caja_min"] == min(p["caja"])


# ---------- Informe PDF ----------
def test_informe_pdf_se_genera(caso):
    from valorix_informe import generar_informe_pdf
    proy = {e: proyectar(caso["res"]["salida"], caso["adic"], e) for e in ESCENARIOS}
    pdf = generar_informe_pdf(caso["calc"], caso["hall"], proy, empresa="Empresa de prueba")
    assert pdf.startswith(b"%PDF") and len(pdf) > 5000


# ---------- Formato ----------
def test_formato_espanol():
    assert n(1234567.891, 1) == "1.234.567,9"
    assert pc(0.1234) == "12,3%"
    assert n(None) == "n/d"


# ---------- Verificación de cifras de los agentes ----------
def test_numeros_entiende_formato_colombiano():
    assert numeros("1.234,5") == [1234.5]
    assert numeros("1,234.5") == [1234.5]


def test_verificar_cifras_detecta_numero_inventado(caso):
    ctx = construir_contexto(caso["calc"], caso["hall"], caso["notas"], caso["hechos"], caso["res"]["salida"],
                             caso["res"]["validaciones"])
    razon = caso["calc"]["m"]["razon_corriente"]["actual"]
    assert verificar_cifras(f"La razón corriente es {razon:.2f}", ctx) == []
    assert verificar_cifras("Hay un faltante de 987654321", ctx) == [987654321.0]
