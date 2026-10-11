"""VALORIX360 · Carga de datos desde Excel o CSV (alternativa al PDF).

Formato: una fila por dato con las columnas Clave (o Dato), Actual y Anterior. Las cifras van en la unidad indicada
(millones de COP por defecto); la fila `dias` es el número de días del periodo y nunca se escala.
"""
import io
import re
import unicodedata

import pandas as pd
from openpyxl import Workbook

from valorix_extractor import parse_numero

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
OBLIGATORIOS = ("efectivo", "cxc", "inventarios", "proveedores", "patrimonio", "ingresos", "costo")
MAX_FILAS = 500


class ErrorCarga(ValueError):
    """Archivo con formato no reconocido; el mensaje es apto para mostrarlo al usuario."""


def _norm(s):
    s = unicodedata.normalize("NFD", str(s).strip().lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def _num(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return parse_numero(str(v).strip())


def plantilla_xlsx():
    """Bytes de un Excel con las filas esperadas, para que el usuario solo digite las cifras."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Datos"
    ws.append(["Clave", "Dato", "Actual", "Anterior"])
    for k, et in ETIQUETAS.items():
        ws.append([k, et, 365 if k == "dias" else None, 365 if k == "dias" else None])
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 18, 42
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _leer_tabla(contenido, nombre):
    try:
        if nombre.lower().endswith(".csv"):
            for enc in ("utf-8-sig", "latin-1"):
                try:
                    return pd.read_csv(io.BytesIO(contenido), sep=None, engine="python", encoding=enc, dtype=object)
                except UnicodeDecodeError:
                    continue
        return pd.read_excel(io.BytesIO(contenido), dtype=object)
    except Exception as e:  # noqa: BLE001
        raise ErrorCarga("No se pudo leer el archivo. Usa la plantilla de datos (Excel) o un CSV con las columnas "
                         "Clave, Dato, Actual y Anterior.") from e


def cargar_tabular(contenido, nombre, factor=1.0):
    """Devuelve un dict con la misma forma que `extraer` + `consolidar`, listo para el diagnóstico.

    factor: multiplicador a millones de COP (1.0 si ya está en millones, 1e-3 si está en miles, 1e-6 en pesos).
    """
    df = _leer_tabla(contenido, nombre)
    if len(df) > MAX_FILAS:
        raise ErrorCarga(f"El archivo tiene demasiadas filas (máximo {MAX_FILAS}).")
    cols = {_norm(c): c for c in df.columns}
    c_act = cols.get("actual")
    c_ant = cols.get("anterior")
    c_id = next((cols[k] for k in ("clave", "dato", "concepto", "cuenta") if k in cols), None)
    if c_act is None or c_id is None:
        raise ErrorCarga("Faltan columnas: se necesitan 'Clave' (o 'Dato') y 'Actual'; 'Anterior' es opcional.")
    por_clave = {k: k for k in ETIQUETAS}
    por_etiqueta = {_norm(v): k for k, v in ETIQUETAS.items()}
    c_dato = cols.get("dato")

    out, meta, avisos, ignoradas = {}, {}, [], []
    for _, fila in df.iterrows():
        k = None
        for celda in (fila[c_id], fila[c_dato] if c_dato is not None else None):
            if celda is not None and not (isinstance(celda, float) and pd.isna(celda)):
                n = _norm(celda)
                k = por_clave.get(n.replace(" ", "_")) or por_etiqueta.get(n)
                if k:
                    break
        if k is None:
            if not pd.isna(fila[c_id]) and str(fila[c_id]).strip():
                ignoradas.append(str(fila[c_id]))
            continue
        esc = 1.0 if k == "dias" else factor
        a, p = _num(fila[c_act]), _num(fila[c_ant]) if c_ant is not None else None
        out[k] = [None if a is None else a * esc, None if p is None else p * esc]
        meta[k] = f"Cargado desde {nombre}"

    faltan = [ETIQUETAS[k] for k in OBLIGATORIOS if out.get(k, [None])[0] is None]
    if faltan:
        raise ErrorCarga("Faltan datos obligatorios del periodo actual: " + ", ".join(faltan) + ".")
    for k in ETIQUETAS:
        out.setdefault(k, [None, None])
    for k in ("otros_ac", "anc", "otros_pc", "pnc", "deuda_lp", "gastos_fin", "impuestos", "da", "capex"):
        out[k] = [0.0 if v is None else v for v in out[k]]
    if out["dias"][0] is None:
        out["dias"] = [365, 365]
        avisos.append("No venían los días del periodo: se asumió año completo (365).")
    elif out["dias"][1] is None:
        out["dias"][1] = out["dias"][0]
    for k in ("gastos_fin", "impuestos", "costo", "da", "capex", "gastos_op"):
        out[k] = [None if v is None else abs(v) for v in out[k]]
    if ignoradas:
        avisos.append("Filas ignoradas por no reconocerse: " + ", ".join(ignoradas[:8]) + ("..." if len(ignoradas) > 8 else ""))
    if out["efectivo"][1] is None:
        avisos.append("No hay periodo anterior: los indicadores comparativos saldrán sin dato.")

    def chk(label, idx):
        g = lambda k: out[k][idx] or 0.0  # noqa: E731
        activos = g("efectivo") + g("cxc") + g("inventarios") + g("otros_ac") + g("anc")
        pasivo_pat = g("oblig_cp") + g("proveedores") + g("otros_pc") + g("pnc") + g("patrimonio")
        ok = abs(activos - pasivo_pat) <= max(0.5, 0.0005 * max(activos, pasivo_pat))
        return (f"Activos = Pasivos + Patrimonio ({label})", round(activos, 2), round(pasivo_pat, 2), "OK" if ok else "REVISAR")

    validaciones = [chk("actual", 0)] + ([chk("anterior", 1)] if out["efectivo"][1] is not None else [])
    return dict(datos={}, log=[], sin_mapear=[], avisos=avisos, factor=factor, unidad="Excel/CSV", i_act=0, years=[None, None],
                fecha_er=None, notas_lineas=[], salida=out, meta=meta, validaciones=validaciones)
