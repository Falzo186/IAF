"""Página Dashboard: filtros, 6 KPIs, tendencia mensual y las 10 necesidades."""

from datetime import date

import streamlit as st

import analytics
from business_queries import BY_ID
from ui import charts, data

SECTIONS = [
    ("Rentabilidad", ["N1", "N4", "N7", "N8"]),
    ("Operación e inventario", ["N2", "N5", "N6", "N9"]),
    ("Personal", ["N3"]),
    ("Riesgo", ["N10"]),
]
CARD_TITLES = {"N5": "Valor de órdenes entregadas tarde"}


def fmt_value(value, fmt: str) -> str:
    if value is None:
        return "—"
    if fmt == "money":
        return f"${value:,.0f}" if abs(value) >= 100_000 else f"${value:,.2f}"
    if fmt == "pct":
        return f"{value:.1f}%"
    return f"{value:,.0f}"


def fmt_delta(kpi: dict) -> str | None:
    if kpi["delta"] is None:
        return None
    return f"{kpi['delta']:+.1f} pp" if kpi["delta_kind"] == "pp" else f"{kpi['delta']:+.1f}%"


# --- Barra superior -------------------------------------------------------------

meta = data.metadata()
d0, d1 = data.default_period()
min_date, max_date = date.fromisoformat(meta["min_order_date"]), date.fromisoformat(meta["reference_date"])

st.markdown("## Dashboard")
c_store, c_dates, c_note = st.columns([1.1, 1.5, 1.6], vertical_alignment="bottom")
store_label = c_store.selectbox("Tienda", ["Todas"] + data.stores(), key="dash_store")
rng = c_dates.date_input("Rango de fechas", value=(d0, d1), min_value=min_date, max_value=max_date,
                         format="DD/MM/YYYY", key="dash_range")
c_note.markdown(f"<div class='inline-note'>Periodo con ventas: {analytics.month_label(d0)} – "
                f"{analytics.month_label(d1)}</div>", unsafe_allow_html=True)

if isinstance(rng, (tuple, list)) and len(rng) == 2:
    date_from, date_to = rng
else:  # el usuario aún no elige la fecha final
    date_from, date_to = (rng[0] if isinstance(rng, (tuple, list)) and rng else d0), d1
store = None if store_label == "Todas" else store_label
f_from, f_to = date_from.isoformat(), date_to.isoformat()

# --- KPIs -----------------------------------------------------------------------

k = data.kpis(store, f_from, f_to)
prev = k["_periodo"]["anterior"]
prev_note = (f"Variación contra {prev[0]:%d/%m/%Y} – {prev[1]:%d/%m/%Y}." if prev
             else "Sin periodo anterior comparable dentro de los datos.")
KPI_HELP = {
    "ingreso_neto": "Suma de net_total de órdenes completadas.",
    "ordenes": "Número de órdenes con estado Completada.",
    "ticket_promedio": "Promedio de net_total por orden completada.",
    "pct_descuento": "Descuento cedido / ingreso bruto en órdenes completadas.",
    "pct_tarde": "Órdenes enviadas después de la fecha requerida / órdenes enviadas.",
    "ingreso_perdido": "Suma de net_total de órdenes rechazadas en el periodo. Hay rechazos "
                       "posteriores a mar 2018: amplía el rango para incluirlos.",
}
with st.container(key="kpis"):
    cols = st.columns(6)
for col, key in zip(cols, analytics.KPI_META):
    kpi = k[key]
    col.metric(kpi["label"], fmt_value(kpi["value"], kpi["fmt"]), fmt_delta(kpi),
               delta_color="normal" if kpi["higher_is_better"] else "inverse",
               help=f"{KPI_HELP[key]} {prev_note}")

# --- Tendencia --------------------------------------------------------------------

with st.container(border=True):
    st.markdown("#### Ingreso neto mensual")
    monthly = data.monthly(store, f_from, f_to)
    if monthly.empty:
        st.info("Sin ventas completadas en el periodo seleccionado.")
    else:
        st.plotly_chart(charts.line(monthly, "mes", "ingreso_neto", money=True, y_title="Ingreso neto",
                                    height=280), config=charts.CONFIG, width="stretch")

# --- Necesidades ------------------------------------------------------------------


def need_card(bq_id: str) -> None:
    bq = BY_ID[bq_id]
    df = data.need(bq_id, store, f_from, f_to)
    with st.container(border=True):
        st.markdown(f"#### {CARD_TITLES.get(bq_id, bq.titulo)}", help=bq.definicion)
        st.markdown(f"<p class='insight'>{analytics.insight(bq_id, df)}</p>", unsafe_allow_html=True)
        if df.empty:
            st.caption("Sin datos para los filtros seleccionados.")
            return
        if bq_id == "N9":
            dim = st.segmented_control("Ver por", ["Categoría", "Marca"], default="Categoría",
                                       key="n9_dim", label_visibility="collapsed") or "Categoría"
            fig = charts.chart_n9(df, dim)
        else:
            fig = charts.NEED_CHARTS[bq_id](df)
        st.plotly_chart(fig, config=charts.CONFIG, width="stretch", key=f"chart_{bq_id}")
        with st.expander("Ver datos"):
            st.dataframe(df, hide_index=True, width="stretch", column_config=charts.column_config(df))
            st.download_button("Descargar CSV", df.to_csv(index=False).encode("utf-8"),
                               file_name=f"{bq_id}_{bq.titulo.lower().replace(' ', '_')}.csv",
                               mime="text/csv", key=f"csv_{bq_id}")


for section, ids in SECTIONS:
    st.markdown(f"<div class='section-title'>{section}</div>", unsafe_allow_html=True)
    for i in range(0, len(ids), 2):
        pair = ids[i:i + 2]
        cols = st.columns(2) if len(pair) == 2 else [st.container()]
        for col, bq_id in zip(cols, pair):
            with col:
                need_card(bq_id)

# --- Panel del equipo ---------------------------------------------------------------
# SOLO para el equipo: genera el PDF de respuestas de referencia (ground truth humano, de
# reference_answers.yaml). No forma parte del análisis ni del Asistente.

st.markdown("<div class='section-title'>Equipo</div>", unsafe_allow_html=True)
with st.expander("Panel del equipo", icon=":material/admin_panel_settings:",
                 expanded="ref_pdf" in st.session_state):
    import reference_report

    st.caption("Herramienta interna. Genera el PDF de respuestas de referencia (redactadas por el "
               "equipo en reference_answers.yaml) con los filtros de tienda y fechas activos. "
               "Es la referencia humana para evaluar en el futuro al asistente; no evalúa al modelo.")
    try:
        pending = reference_report.unapproved(reference_report.load_answers())
    except Exception as exc:  # YAML mal editado: se avisa sin romper el dashboard
        pending = None
        st.error(f"reference_answers.yaml no es válido: {exc}")
    if pending:
        st.warning(f"{len(pending)} de 10 respuestas de referencia están sin aprobar. "
                   "El PDF las marcará como borrador.")
    if pending is not None and st.button("Generar PDF de referencia", key="gen_ref_pdf"):
        with st.spinner("Generando el PDF (unos 30 s: se exportan las 10 gráficas)…"):
            st.session_state["ref_pdf"] = reference_report.generar_pdf_referencia(store, f_from, f_to)
    if "ref_pdf" in st.session_state:
        st.download_button("Descargar PDF de referencia", st.session_state["ref_pdf"],
                           file_name=reference_report.default_filename(), mime="application/pdf",
                           key="dl_ref_pdf", icon=":material/download:")
