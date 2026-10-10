"""Prueba rápida de punta a punta (sin Streamlit): PDF -> extracción -> motor -> agentes -> Excel.
Ejecuta:  python probar.py [ruta_pdf]"""
import sys
from pathlib import Path

from valorix_agentes import consultar_agente, construir_contexto
from valorix_extractor import consolidar, escribir_plantilla, extraer, segmentar_notas
from valorix_motor import ADIC_SPEC, ESCENARIOS, calcular, extraer_hechos, generar_hallazgos, proyectar

pdf = sys.argv[1] if len(sys.argv) > 1 else "ejemplos/ejemplo_estados_financieros.pdf"
res = extraer(pdf)
consolidar(res)
notas = segmentar_notas(res["notas_lineas"])
out = res["salida"]
adic = {k: defecto for k, _, _, _, defecto in ADIC_SPEC}
hechos = extraer_hechos(notas, 1e-3)
calc = calcular(out, adic)
hall = generar_hallazgos(calc, hechos, res["validaciones"])
ctx = construir_contexto(calc, hall, notas, hechos, out, res["validaciones"])
proy = {e: proyectar(out, adic, e) for e in ESCENARIOS}

malas = [v for v in res["validaciones"] if v[3] == "REVISAR"]
print(f"Periodos: {res['years']} · notas: {len(notas)} · indicadores: {len(calc['m'])}")
print(f"Validaciones: {len(res['validaciones']) - len(malas)} OK, {len(malas)} por revisar")
print("Escenarios proyectados:", ", ".join(proy))
r = consultar_agente("financiero", "¿Cómo está mi liquidez?", ctx, [], usar_ia=False)
print("Agente financiero (reglas):", r["texto"][:160].replace("\n", " "), "...")

Path("salidas").mkdir(exist_ok=True)
filas = {fila: adic.get(k) for k, _, fila, _, _ in ADIC_SPEC}
escribir_plantilla(res, notas, "valorix360_plantilla_diagnostico.xlsx", "salidas/prueba.xlsx", adic_filas=filas)
print("OK -> salidas/prueba.xlsx")
