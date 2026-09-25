"""PDF de respuestas de referencia (ground truth humano) para las 10 necesidades.

Sin Streamlit: se usa desde la CLI y desde el Panel del equipo del dashboard.
    python reference_report.py [--tienda "Baldwin Bikes"] [--desde 2017-01-01] [--hasta 2017-12-31]
genera reportes/referencia_bikestores_<fecha>.pdf.

Para cada necesidad N1–N10: pregunta de negocio y respuesta de referencia (de
reference_answers.yaml, redactadas por el equipo), definición y SQL verificada (de
business_queries.py), la gráfica del dashboard (ui/charts.py, exportada a PNG con kaleido)
y una tabla resumen. Las respuestas con `aprobado: false` llevan una franja diagonal
"BORRADOR — PENDIENTE DE REVISIÓN". Este documento NO evalúa al modelo de IA.
"""

from __future__ import annotations

import argparse
import hashlib
import io
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
import yaml
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Flowable, Image, PageBreak, Paragraph, Preformatted,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

import analytics
import config
from business_queries import BY_ID, render_sql
from sql_engine import format_value
from ui import charts

ANSWERS_PATH = config.BASE_DIR / "reference_answers.yaml"
REPORTS_DIR = config.BASE_DIR / "reportes"
NEED_IDS = [f"N{i}" for i in range(1, 11)]
REQUIRED_FIELDS = ("pregunta", "respuesta_referencia", "autor", "fecha_revision", "aprobado")
DRAFT_LABEL = "BORRADOR — PENDIENTE DE REVISIÓN"
TEAM_PLACEHOLDER = "[Nombre 1] · [Nombre 2]"
TABLE_ROWS = 10

# Paleta del dashboard adaptada a papel blanco: texto oscuro y el mismo acento.
INK = colors.HexColor("#1f1f24")
INK_MUTED = colors.HexColor("#5f5f68")
ACCENT = colors.HexColor(charts.ACCENT)
RULE = colors.HexColor("#d9d9de")
SOFT = colors.HexColor("#f4f5f8")
DRAFT_RED = colors.HexColor("#c0392b")


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------

def load_answers(path: Path = ANSWERS_PATH) -> dict:
    """Lee reference_answers.yaml y valida que estén N1–N10 con los 5 campos."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    missing = [n for n in NEED_IDS if n not in data]
    if missing:
        raise ValueError(f"{Path(path).name}: faltan las necesidades {missing}")
    for n in NEED_IDS:
        lacking = [f for f in REQUIRED_FIELDS if f not in (data[n] or {})]
        if lacking:
            raise ValueError(f"{Path(path).name}: {n} no tiene los campos {lacking}")
    return data


def unapproved(answers: dict) -> list[str]:
    return [n for n in NEED_IDS if answers[n].get("aprobado") is not True]


def db_short_hash(path: Path = config.DB_PATH) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def _period(store, date_from, date_to) -> tuple[str, str, str]:
    d0, d1 = analytics.default_period()
    f = date.fromisoformat(str(date_from)) if date_from else d0
    t = date.fromisoformat(str(date_to)) if date_to else d1
    label = f"{f:%d/%m/%Y} – {t:%d/%m/%Y} · Tienda: {store or 'Todas'}"
    return f.isoformat(), t.isoformat(), label


# ---------------------------------------------------------------------------
# Gráficas: plantilla del dashboard pasada a fondo blanco
# ---------------------------------------------------------------------------

def _print_figure(fig):
    """Misma gráfica del dashboard, legible en papel: fondo blanco y texto oscuro."""
    dark, muted, grid = "#1f1f24", "#5f5f68", "rgba(0,0,0,0.10)"
    fig.update_layout(paper_bgcolor="white", plot_bgcolor="white", font=dict(color=dark),
                      legend=dict(font=dict(color=muted)),
                      margin=dict(l=8, r=70, t=30 if fig.layout.showlegend else 8, b=48))
    fig.update_xaxes(gridcolor=grid, linecolor=grid, tickfont=dict(color=muted),
                     title_font=dict(color=muted))
    fig.update_yaxes(gridcolor=grid, linecolor=grid, tickfont=dict(color=dark),
                     title_font=dict(color=muted))
    fig.update_traces(textfont=dict(color=muted), selector=dict(type="bar"))
    return fig


_PNG_CACHE: dict[tuple, bytes] = {}   # (necesidad, tienda, desde, hasta, hash BD) -> PNG


def chart_png(bq_id: str, df: pd.DataFrame, width_px: int = 1000, cache_key: tuple | None = None
              ) -> bytes | None:
    """PNG de la gráfica del dashboard. Exportar con kaleido tarda ~3 s por gráfica, así que
    se cachea por necesidad + filtros + hash de la BD (mismos datos -> misma imagen)."""
    if df.empty:
        return None
    if cache_key is not None and cache_key in _PNG_CACHE:
        return _PNG_CACHE[cache_key]
    png = _render_chart(bq_id, df, width_px)
    if cache_key is not None:
        _PNG_CACHE[cache_key] = png
    return png


def _render_chart(bq_id: str, df: pd.DataFrame, width_px: int) -> bytes:
    fig = charts.chart_n9(df, "Categoría") if bq_id == "N9" else charts.NEED_CHARTS[bq_id](df)
    fig = _print_figure(fig)
    height = int(fig.layout.height or 320) + 40
    return fig.to_image(format="png", width=width_px, height=height, scale=2)


# ---------------------------------------------------------------------------
# Elementos del PDF
# ---------------------------------------------------------------------------

def _styles() -> dict:
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=10,
                          leading=14, textColor=INK)
    return {
        "title": ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=24,
                                leading=30, spaceAfter=10),
        "subtitle": ParagraphStyle("subtitle", parent=body, fontSize=13, leading=18,
                                   textColor=INK_MUTED),
        "h1": ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=16,
                             leading=21, spaceAfter=4),
        "question": ParagraphStyle("question", parent=body, fontName="Helvetica-Oblique",
                                   fontSize=11, leading=15, textColor=ACCENT, spaceAfter=6),
        "small": ParagraphStyle("small", parent=body, fontSize=8, leading=11, textColor=INK_MUTED),
        "body": body,
        "box_title": ParagraphStyle("box_title", parent=body, fontName="Helvetica-Bold",
                                    fontSize=9, leading=12, textColor=ACCENT),
        "note": ParagraphStyle("note", parent=body, fontSize=10, leading=14, borderColor=RULE,
                               borderWidth=0.8, borderPadding=8, backColor=SOFT),
        "center": ParagraphStyle("center", parent=body, alignment=TA_CENTER),
        "mono": ParagraphStyle("mono", fontName="Courier", fontSize=7.2, leading=9, textColor=INK),
    }


class ReferenceBox(Flowable):
    """Recuadro "RESPUESTA DE REFERENCIA (equipo)"; si no está aprobado, franja de borrador."""

    def __init__(self, text: str, answer: dict, styles: dict, width: float):
        super().__init__()
        meta = (f"Autor: {escape(answer.get('autor') or '—')} · Revisión: "
                f"{escape(str(answer.get('fecha_revision') or '—'))} · "
                f"{'Aprobado' if answer.get('aprobado') is True else 'Sin aprobar'}")
        rows = [[Paragraph("RESPUESTA DE REFERENCIA (equipo)", styles["box_title"])],
                [Paragraph(escape(text.strip()).replace("\n", " "), styles["body"])],
                [Paragraph(meta, styles["small"])]]
        self.approved = answer.get("aprobado") is True
        self.table = Table(rows, colWidths=[width])
        self.table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1.2, ACCENT if self.approved else DRAFT_RED),
            ("BACKGROUND", (0, 0), (-1, -1), SOFT),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))

    def wrap(self, avail_width, avail_height):
        self.w, self.h = self.table.wrap(avail_width, avail_height)
        return self.w, self.h

    def draw(self):
        self.table.drawOn(self.canv, 0, 0)
        if self.approved:
            return
        c = self.canv
        c.saveState()
        c.translate(self.w / 2, self.h / 2)
        c.rotate(18)
        c.setFillColor(DRAFT_RED)
        c.setFillAlpha(0.14)
        c.rect(-self.w * 0.62, -15, self.w * 1.24, 30, stroke=0, fill=1)
        c.setFillAlpha(0.55)
        c.setFont("Helvetica-Bold", 17)
        c.drawCentredString(0, -6, DRAFT_LABEL)
        c.restoreState()


def _data_table(df: pd.DataFrame, styles: dict, width: float) -> Table:
    shown = df.head(TABLE_ROWS)
    cols = [str(c) for c in shown.columns]
    header = [Paragraph(f"<b>{escape(c.replace('_', ' ').capitalize())}</b>", styles["small"])
              for c in cols]
    body = [[Paragraph(escape(format_value(v.item() if hasattr(v, "item") else v, c)), styles["small"])
             for v, c in zip(row, cols)] for row in shown.itertuples(index=False)]
    # Ancho de cada columna proporcional a su texto más largo (encabezado o valor), con un
    # tope para que un nombre de producto largo no aplaste a las columnas de montos.
    texts = [[format_value(v.item() if hasattr(v, "item") else v, c) for v in shown[c]] for c in shown.columns]
    weights = [min(max([len(t) for t in col] + [len(c) * 0.8]) + 3, 34) for c, col in zip(cols, texts)]
    col_widths = [width * w / sum(weights) for w in weights]
    table = Table([header] + body, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK), ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return table


# ---------------------------------------------------------------------------
# Documento
# ---------------------------------------------------------------------------

def generar_pdf_referencia(store: str | None = None, date_from=None, date_to=None,
                           answers_path: Path = ANSWERS_PATH) -> bytes:
    """Genera el PDF de referencia y devuelve sus bytes (no escribe en disco)."""
    answers = load_answers(answers_path)
    pending = unapproved(answers)
    f_from, f_to, period_label = _period(store, date_from, date_to)
    db_hash = db_short_hash()
    generated = datetime.now()
    st = _styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                            title="Bike Stores Analytics — Respuestas de referencia",
                            author=TEAM_PLACEHOLDER)
    width = doc.width

    def footer(canv, d):
        canv.saveState()
        canv.setFont("Helvetica", 7.5)
        canv.setFillColor(INK_MUTED)
        canv.drawString(d.leftMargin, 0.9 * cm,
                        f"Bike Stores Analytics — Respuestas de referencia · BD sha256:{db_hash}")
        canv.drawRightString(d.leftMargin + d.width, 0.9 * cm, f"Página {d.page}")
        canv.restoreState()

    story = [Spacer(1, 4 * cm),
             Paragraph("Bike Stores Analytics — Respuestas de referencia", st["title"]),
             Paragraph(TEAM_PLACEHOLDER, st["subtitle"]), Spacer(1, 0.6 * cm),
             Paragraph(f"<b>Generado:</b> {generated:%d/%m/%Y %H:%M}", st["body"]),
             Paragraph(f"<b>Periodo de datos analizado:</b> {escape(period_label)}", st["body"]),
             Paragraph(f"<b>Base de datos:</b> bikestores.db · sha256 {db_hash}", st["body"]),
             Spacer(1, 0.8 * cm),
             Paragraph("Este documento es la referencia humana para evaluar en el futuro la "
                       "precisión del asistente conversacional. No es una evaluación del modelo "
                       "de IA.", st["note"]),
             Spacer(1, 0.5 * cm)]
    if pending:
        story.append(Paragraph(
            f"<font color='#c0392b'><b>{len(pending)} de 10 respuestas de referencia están sin "
            f"aprobar</b> ({', '.join(pending)}) y se marcan como {DRAFT_LABEL}.</font>",
            st["body"]))
    story.append(Paragraph(
        "Las respuestas de referencia describen el periodo completo con ventas y todas las "
        "tiendas; las gráficas y tablas usan los filtros indicados arriba.", st["small"]))

    for n in NEED_IDS:
        bq, ans = BY_ID[n], answers[n]
        df = analytics.need(n, store, f_from, f_to)
        story += [PageBreak(),
                  Paragraph(f"Necesidad {n[1:]} — {escape(bq.titulo)}", st["h1"]),
                  Paragraph(escape(ans["pregunta"]), st["question"]),
                  Paragraph(f"<b>Definición operativa.</b> {escape(bq.definicion)}", st["small"]),
                  Paragraph(f'SQL verificada: <a href="#sql_{n}" color="#3987e5">ver Apéndice A.{n[1:]}</a>',
                            st["small"]),
                  Spacer(1, 0.3 * cm)]
        png = chart_png(n, df, cache_key=(n, store, f_from, f_to, db_hash))
        if png:
            img = Image(io.BytesIO(png))
            scale = min(width / img.imageWidth, 6.2 * cm / img.imageHeight)
            img.drawWidth, img.drawHeight = img.imageWidth * scale, img.imageHeight * scale
            story += [img, Spacer(1, 0.2 * cm)]
        else:
            story.append(Paragraph("Sin datos para los filtros seleccionados.", st["small"]))
        if not df.empty:
            story += [_data_table(df, st, width),
                      Paragraph(f"Primeras {min(len(df), TABLE_ROWS)} de {len(df):,} filas.", st["small"])]
        story += [Spacer(1, 0.4 * cm), ReferenceBox(ans["respuesta_referencia"], ans, st, width)]

    story += [PageBreak(), Paragraph("Apéndice A — Consultas SQL verificadas", st["h1"]),
              Paragraph("Tal como se ejecutaron para este documento (con los filtros incrustados).",
                        st["small"]), Spacer(1, 0.3 * cm)]
    for n in NEED_IDS:
        sql = render_sql(BY_ID[n], store_name=store, date_from=f_from if date_from else None,
                         date_to=f_to if date_to else None)
        story += [Paragraph(f'<a name="sql_{n}"/>A.{n[1:]} · {n} — {escape(BY_ID[n].titulo)}',
                            st["box_title"]),
                  Preformatted(sql, st["mono"]), Spacer(1, 0.35 * cm)]

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def default_filename(day: date | None = None) -> str:
    return f"referencia_bikestores_{(day or date.today()):%Y-%m-%d}.pdf"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Genera el PDF de respuestas de referencia.")
    ap.add_argument("--tienda", default=None)
    ap.add_argument("--desde", default=None, help="AAAA-MM-DD")
    ap.add_argument("--hasta", default=None, help="AAAA-MM-DD")
    args = ap.parse_args(argv)
    REPORTS_DIR.mkdir(exist_ok=True)
    out = REPORTS_DIR / default_filename()
    out.write_bytes(generar_pdf_referencia(args.tienda, args.desde, args.hasta))
    pending = unapproved(load_answers())
    print(f"PDF: {out} ({out.stat().st_size / 1024:.0f} KB)")
    if pending:
        print(f"{len(pending)} de 10 respuestas sin aprobar ({', '.join(pending)}): marcadas como borrador.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
