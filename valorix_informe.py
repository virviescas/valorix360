"""VALORIX360 · Informe de diagnóstico en PDF (resumen ejecutivo, indicadores, plan, covenants y proyección)."""
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from valorix_motor import fmt_valor, mm

INK, LIME, GRIS = colors.HexColor("#0a0a0f"), colors.HexColor("#c6f432"), colors.HexColor("#5b5f69")
SEMAFORO = {"ok": colors.HexColor("#3f8f00"), "atencion": colors.HexColor("#d98200"), "riesgo": colors.HexColor("#d12f2f")}
TEXTO_SEMAFORO = {"ok": "Bien", "atencion": "Atención", "riesgo": "Riesgo"}
NOMBRES = {"contable": "Contable", "financiero": "Financiero", "cumplimiento": "Cumplimiento y riesgos"}
AVISO = ("Herramienta de apoyo a la decisión. No constituye auditoría, revisoría fiscal, dictamen ni asesoría legal o tributaria. "
         "Las cifras provienen de los estados financieros entregados por la empresa y no fueron auditadas por Valorix360.")


def _t(texto):
    """Escapa para Paragraph y sustituye símbolos que la fuente estándar no dibuja."""
    s = str(texto).replace("\u2212", "-").replace("\u2248", "aprox. ").replace("\u2265", ">=").replace("\u2264", "<=")
    return escape(s)


def _estilos():
    base = getSampleStyleSheet()
    return dict(
        h1=ParagraphStyle("h1", parent=base["Heading1"], fontSize=20, textColor=INK, spaceAfter=6),
        h2=ParagraphStyle("h2", parent=base["Heading2"], fontSize=13, textColor=INK, spaceBefore=14, spaceAfter=6),
        p=ParagraphStyle("p", parent=base["BodyText"], fontSize=9.5, leading=13),
        small=ParagraphStyle("small", parent=base["BodyText"], fontSize=8, leading=10, textColor=GRIS),
        celda=ParagraphStyle("celda", parent=base["BodyText"], fontSize=8.5, leading=10.5),
    )


def _tabla(filas, anchos, cabecera=True):
    t = Table(filas, colWidths=anchos, repeatRows=1 if cabecera else 0)
    estilo = [("FONTSIZE", (0, 0), (-1, -1), 8.5), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f5f7")]),
              ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e4e6ea")),
              ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if cabecera:
        estilo += [("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), LIME),
                   ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    t.setStyle(TableStyle(estilo))
    return t


def _pie(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GRIS)
    canvas.drawString(2 * cm, 1.2 * cm, "Valorix360 · Diagnóstico financiero")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
    canvas.restoreState()


def generar_informe_pdf(calc, hall, proy, empresa="Cliente", escenario="Base"):
    """Devuelve los bytes del PDF. calc/hall vienen del motor; proy es {escenario: proyección}."""
    e = _estilos()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                            title=f"Diagnóstico financiero · {empresa}", author="Valorix360")
    P = lambda txt, st="p": Paragraph(_t(txt), e[st])
    h = []

    # Portada y resumen ejecutivo
    h += [Paragraph("VALORIX <font color='#7aa800'>360</font>", e["h2"]), Spacer(1, 1.2 * cm),
          P("Informe de diagnóstico financiero y estratégico", "h1"),
          P(f"{empresa} · {date.today().strftime('%d/%m/%Y')} · Referencias: {calc.get('sector', 'General')}", "small"), Spacer(1, 0.6 * cm),
          P("Resumen ejecutivo", "h2")]
    filas = [["Área", "Estado", "Conclusión"]]
    for ag, v in hall["veredictos"].items():
        filas.append([P(NOMBRES[ag], "celda"), TEXTO_SEMAFORO[v["estado"]], P(v["titular"], "celda")])
    t = _tabla(filas, [4.2 * cm, 2.6 * cm, 10.2 * cm])
    for i, v in enumerate(hall["veredictos"].values(), 1):
        t.setStyle(TableStyle([("TEXTCOLOR", (1, i), (1, i), SEMAFORO[v["estado"]])]))
    h += [t, Spacer(1, 0.4 * cm)]
    for ag, v in hall["veredictos"].items():
        h.append(Paragraph(f"<b>{_t(NOMBRES[ag])}.</b> {_t(v['texto'])}", e["p"]))
        h.append(Spacer(1, 0.15 * cm))

    # Plan de acción
    h.append(P("Plan de acción priorizado", "h2"))
    if hall["plan"]:
        filas = [["#", "Acción", "Impacto aprox."]]
        for i, p in enumerate(hall["plan"], 1):
            filas.append([str(i), P(f"{p['accion']} ({p['titulo']})", "celda"), mm(p["impacto_m"]) if p["impacto_m"] else "-"])
        h.append(_tabla(filas, [0.8 * cm, 12.7 * cm, 3.5 * cm]))
    else:
        h.append(P("No hay acciones pendientes con la información cargada."))

    # Indicadores
    h += [PageBreak(), P("Indicadores", "h1")]
    grupos = []
    for m in calc["metricas"]:
        if m["grupo"] not in grupos:
            grupos.append(m["grupo"])
    for g in grupos:
        h.append(P(g, "h2"))
        filas = [["Indicador", "Actual", "Anterior", "Referencia", "Estado"]]
        for m in (x for x in calc["metricas"] if x["grupo"] == g):
            filas.append([P(m["nombre"], "celda"), fmt_valor(m["actual"], m["fmt"]), fmt_valor(m["anterior"], m["fmt"]),
                          fmt_valor(m["ref"], m["fmt"]) if m["ref"] is not None else "", m["estado"] if m["ref"] is not None else ""])
        h.append(_tabla(filas, [7.2 * cm, 2.6 * cm, 2.6 * cm, 2.6 * cm, 2 * cm]))

    # Covenants y estrés
    h.append(P("Covenants", "h2"))
    filas = [["Covenant", "Actual", "Límite", "Resultado"]]
    for c in calc["covenants"]:
        res = "Sin dato" if c["cumple"] is None else ("Cumple" if c["cumple"] else "INCUMPLE")
        filas.append([P(c["nombre"], "celda"), fmt_valor(c["actual"], c["fmt"]), fmt_valor(c["limite"], c["fmt"]), res])
    h.append(_tabla(filas, [8 * cm, 3 * cm, 3 * cm, 3 * cm]))

    # Proyección
    h += [PageBreak(), P("Proyección de caja a 12 meses", "h1")]
    meses = (3, 6, 9, 12)
    filas = [["Escenario"] + [f"Mes {m}" for m in meses] + ["Mínima", "Mes mín."]]
    for nombre, p in proy.items():
        filas.append([nombre] + [f"{p['caja'][m - 1]:,.0f}".replace(",", ".") for m in meses]
                     + [f"{p['caja_min']:,.0f}".replace(",", "."), str(p["mes_min"])])
    h.append(_tabla(filas, [3.4 * cm, 2.4 * cm, 2.4 * cm, 2.4 * cm, 2.4 * cm, 2.4 * cm, 1.6 * cm]))
    sel = proy.get(escenario) or next(iter(proy.values()))
    h += [Spacer(1, 0.3 * cm),
          P(f"Cifras en millones de COP. Caja de seguridad de referencia (30 días de costos y gastos): {mm(sel['caja_seguridad'])}. "
            + ("En el escenario " + escenario + " la caja mínima queda por debajo de ese nivel." if sel["bajo_seguridad"]
               else "En el escenario " + escenario + " la caja se mantiene por encima de ese nivel."), "p"),
          P("Modelo simplificado: costos fijos constantes y sin estacionalidad. No garantiza resultados futuros.", "small"),
          Spacer(1, 0.8 * cm), P("Aviso importante", "h2"), P(AVISO, "small")]

    doc.build(h, onFirstPage=_pie, onLaterPages=_pie)
    return buf.getvalue()
