"""Plantilla Plotly oscura compartida y gráficos del dashboard y del asistente.

Reglas: rankings en barras horizontales ordenadas; el elemento destacado va en el
color de acento y el resto en gris; moneda con $ y separador de miles; etiquetas
en español; sin arcoíris, sin 3D y sin pies. Paleta validada contra la superficie
#17171a (scripts/validate_palette.js de la guía dataviz): acento #3987e5, gris
#6f6f7a (contraste >= 3:1) y naranja #d95926 como 2.ª categoría (ΔE CVD 26.8).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

ACCENT = "#3987e5"
MUTED = "#6f6f7a"
SECOND = "#d95926"
TEXT = "#ececec"
TEXT_MUTED = "#9a9aa3"
GRID = "rgba(255,255,255,0.07)"
SURFACE = "#17171a"
FONT = "Inter, -apple-system, 'Segoe UI', Roboto, sans-serif"

TEMPLATE = go.layout.Template(
    layout=dict(
        font=dict(family=FONT, color=TEXT, size=13),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=[ACCENT, SECOND, MUTED],
        separators=".,",
        margin=dict(l=8, r=16, t=8, b=8),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor="#2a2a30", font=dict(family=FONT, color=TEXT)),
        xaxis=dict(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=TEXT_MUTED),
                   title=dict(font=dict(color=TEXT_MUTED, size=12))),
        yaxis=dict(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=TEXT_MUTED),
                   title=dict(font=dict(color=TEXT_MUTED, size=12))),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=TEXT_MUTED),
                    bgcolor="rgba(0,0,0,0)"),
        bargap=0.35,
    )
)
pio.templates["bikestores"] = TEMPLATE

CONFIG = {"displayModeBar": False, "locale": "es"}


def _money_axis(axis: dict) -> dict:
    # Abreviado en el eje ($500k, $1.5M); la cifra exacta va en la etiqueta y el tooltip.
    return {**axis, "tickprefix": "$", "tickformat": "~s", "nticks": 5}


def _truncate(label: str, n: int = 34) -> str:
    label = str(label)
    return label if len(label) <= n else label[: n - 1] + "…"


def hbar(df: pd.DataFrame, label: str, value: str, *, money: bool = False, pct: bool = False,
         highlight: str = "max", value_title: str = "", colors: list[str] | None = None,
         hover_extra: str = "", height: int | None = None, text_fmt: str | None = None) -> go.Figure:
    """Ranking en barras horizontales ordenadas (el mayor arriba) con un destacado en acento."""
    d = df.copy()
    ascending_display = True  # plotly dibuja de abajo hacia arriba
    d = d.sort_values(value, ascending=ascending_display)
    if colors is None:
        target = d[value].max() if highlight == "max" else d[value].min()
        colors = [ACCENT if v == target else MUTED for v in d[value]]
    if text_fmt is None:
        text_fmt = "$%{x:,.0f}" if money else ("%{x:.1f}%" if pct else "%{x:,.0f}")
    fig = go.Figure(go.Bar(
        x=d[value], y=[_truncate(v) for v in d[label]], orientation="h",
        marker=dict(color=colors, cornerradius=4), texttemplate=text_fmt, textposition="outside",
        textfont=dict(color=TEXT_MUTED, size=12), cliponaxis=False,
        customdata=d[label],
        hovertemplate=f"<b>%{{customdata}}</b><br>{value_title or value}: "
                      + ("$%{x:,.2f}" if money else ("%{x:.2f}%" if pct else "%{x:,}"))
                      + hover_extra + "<extra></extra>",
    ))
    xaxis = dict(title=value_title, showgrid=True, rangemode="tozero")
    if money:
        xaxis = _money_axis(xaxis)
    if pct:
        xaxis["ticksuffix"] = "%"
    fig.update_layout(template="bikestores", xaxis=xaxis, yaxis=dict(title="", automargin=True),
                      height=height or max(220, 34 * len(d) + 60), showlegend=False,
                      margin=dict(l=8, r=64, t=8, b=8))
    return fig


def vbar(df: pd.DataFrame, x: str, y: str, *, money: bool = False, highlight: str = "max",
         x_title: str = "", y_title: str = "", height: int = 300) -> go.Figure:
    target = df[y].max() if highlight == "max" else df[y].min()
    colors = [ACCENT if v == target else MUTED for v in df[y]]
    fig = go.Figure(go.Bar(
        x=df[x].astype(str), y=df[y], marker=dict(color=colors, cornerradius=4),
        hovertemplate="<b>%{x}</b><br>" + (y_title or y) + ": "
                      + ("$%{y:,.2f}" if money else "%{y:,}") + "<extra></extra>",
    ))
    yaxis = dict(title=y_title, rangemode="tozero")
    labels = df[x].astype(str).tolist()
    step = max(1, len(labels) // 8)
    fig.update_layout(template="bikestores",
                      xaxis=dict(title=x_title, type="category", tickmode="array",
                                 tickvals=labels[::step], ticktext=labels[::step], tickangle=0),
                      yaxis=_money_axis(yaxis) if money else yaxis, height=height, showlegend=False)
    return fig


MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def spanish_period(value) -> str:
    """'2017-03' o '2017-03-15' -> 'mar 2017'; cualquier otro valor se devuelve igual."""
    s = str(value)
    if len(s) >= 7 and s[4] == "-" and s[:4].isdigit() and s[5:7].isdigit():
        return f"{MONTHS_ES[int(s[5:7]) - 1]} {s[:4]}" + (f" {s[8:10]}" if len(s) >= 10 else "")
    return s


def line(df: pd.DataFrame, x: str, y: str, *, money: bool = False, x_title: str = "",
         y_title: str = "", height: int = 300) -> go.Figure:
    # Eje categórico con etiquetas en español (Plotly no trae el locale "es" en Streamlit).
    labels = [spanish_period(v) for v in df[x]]
    step = max(1, len(labels) // 9)
    fig = go.Figure(go.Scatter(
        x=labels, y=df[y], mode="lines+markers", line=dict(color=ACCENT, width=2),
        marker=dict(size=7, color=ACCENT), fill="tozeroy", fillcolor="rgba(57,135,229,0.10)",
        cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>" + (y_title or y) + ": "
                      + ("$%{y:,.2f}" if money else "%{y:,}") + "<extra></extra>",
    ))
    yaxis = dict(title=y_title, rangemode="tozero")
    fig.update_layout(template="bikestores",
                      xaxis=dict(title=x_title, showgrid=False, type="category",
                                 tickmode="array", tickvals=labels[::step], ticktext=labels[::step],
                                 range=[-0.5, len(labels) - 0.5]),
                      yaxis=_money_axis(yaxis) if money else yaxis, height=height,
                      hovermode="x unified", showlegend=False, margin=dict(l=8, r=24, t=8, b=8))
    return fig


# ---------------------------------------------------------------------------
# Gráficos de las 10 necesidades
# ---------------------------------------------------------------------------

def chart_n1(df):
    top = df[df["ranking"] == "Top ingreso neto"]
    return hbar(top, "producto", "ingreso_neto", money=True, value_title="Ingreso neto")


def chart_n2(df):
    d = df.assign(caso=df["producto"].map(_truncate) + " · " + df["tienda"].str.replace(" Bikes", ""))
    # plotly dibuja de abajo hacia arriba: los agotados (stock 0) quedan arriba
    d = d.sort_values(["stock", "unidades_vendidas"], ascending=[False, True])
    colors = [ACCENT if s == 0 else MUTED for s in d["stock"]]
    fig = go.Figure(go.Bar(
        x=[max(s, 0.12) for s in d["stock"]], y=d["caso"], orientation="h",
        marker=dict(color=colors, cornerradius=4),
        text=["agotado" if s == 0 else f"{int(s)} u." for s in d["stock"]], textposition="outside",
        cliponaxis=False,
        textfont=dict(color=TEXT_MUTED, size=12), customdata=d["unidades_vendidas"],
        hovertext=[f"Stock: {int(s)} u." for s in d["stock"]],
        hovertemplate="<b>%{y}</b><br>%{hovertext}<br>Unidades vendidas: %{customdata:,}<extra></extra>",
    ))
    fig.update_layout(template="bikestores", xaxis=dict(title="Unidades en stock (en azul: agotado)",
                      range=[0, 5.5], dtick=1), yaxis=dict(title="", automargin=True),
                      height=max(220, 34 * len(d) + 60), margin=dict(l=8, r=48, t=8, b=8))
    return fig


def chart_n3(df):
    return hbar(df, "vendedor", "ingreso_neto", money=True, value_title="Ingreso neto en Electric Bikes")


def chart_n4(df):
    d = df.assign(ciudad_estado=df["ciudad"] + ", " + df["estado"])
    return hbar(d, "ciudad_estado", "pct_ingreso_desc_minimo", pct=True,
                value_title="% del ingreso de la ciudad con descuento mínimo")


def chart_n5(df):
    stores = df[df["tienda"] != "Total"]
    return hbar(stores, "tienda", "monto_neto", money=True, value_title="Valor de órdenes entregadas tarde",
                height=220)


def chart_n6(df, top: int = 15):
    d = df.sort_values("valor_inmovilizado", ascending=False).head(top)
    fig = go.Figure()
    for estado, color in (("Nunca vendido", ACCENT), ("Sin ventas recientes", SECOND)):
        part = d[d["estado_inventario"] == estado]
        fig.add_trace(go.Bar(
            x=part["valor_inmovilizado"], y=[_truncate(p) for p in part["producto"]], orientation="h",
            name=estado, marker=dict(color=color, cornerradius=4),
            customdata=part["unidades_inmovilizadas"],
            hovertemplate="<b>%{y}</b><br>Valor inmovilizado: $%{x:,.2f}<br>Unidades: %{customdata:,}"
                          f"<br>{estado}<extra></extra>",
        ))
    order = [_truncate(p) for p in d.sort_values("valor_inmovilizado")["producto"]]
    fig.update_layout(template="bikestores", barmode="overlay",
                      xaxis=_money_axis(dict(title="Valor inmovilizado a precio de lista", rangemode="tozero")),
                      yaxis=dict(title="", categoryorder="array", categoryarray=order, automargin=True),
                      height=max(260, 30 * len(d) + 80), showlegend=True)
    return fig


def chart_n7(df):
    dist = df.groupby("max_marcas").size().reset_index(name="clientes")
    dist["max_marcas"] = dist["max_marcas"].astype(int).astype(str) + " marcas"
    return vbar(dist, "max_marcas", "clientes", x_title="Máximo de marcas en una orden",
                y_title="Clientes", height=260)


def chart_n8(df):
    return hbar(df, "tienda", "ticket_promedio", money=True, value_title="Ticket promedio", height=220)


def chart_n9(df, dimension: str = "Categoría"):
    d = df[df["dimension"] == dimension]
    return hbar(d, "nombre", "rotacion_mensual", highlight="min", value_title="Unidades vendidas por mes",
                text_fmt="%{x:.1f}")


def chart_n10(df):
    months = df[df["nivel"] == "Mes"].rename(columns={"detalle": "mes"})
    months = months.assign(mes=months["mes"].map(spanish_period))
    return vbar(months, "mes", "monto_neto_perdido", money=True, x_title="Mes",
                y_title="Monto neto perdido", height=280)


NEED_CHARTS = {"N1": chart_n1, "N2": chart_n2, "N3": chart_n3, "N4": chart_n4, "N5": chart_n5,
               "N6": chart_n6, "N7": chart_n7, "N8": chart_n8, "N9": chart_n9, "N10": chart_n10}


# ---------------------------------------------------------------------------
# Formato de tablas
# ---------------------------------------------------------------------------

def column_config(df: pd.DataFrame) -> dict:
    """st.column_config con $ y separador de miles para dinero y % para porcentajes."""
    import streamlit as st  # import local: este módulo también se usa sin Streamlit

    cfg = {}
    for col in df.columns:
        name = str(col).lower()
        label = str(col).replace("_", " ").capitalize()
        if not pd.api.types.is_numeric_dtype(df[col]):
            cfg[col] = st.column_config.TextColumn(label)
        elif "pct" in name or "porcentaje" in name:
            cfg[col] = st.column_config.NumberColumn(label, format="%.1f%%")
        elif any(h in name for h in _MONEY_HINT):
            cfg[col] = st.column_config.NumberColumn(label, format="dollar")
        elif pd.api.types.is_integer_dtype(df[col]):
            cfg[col] = st.column_config.NumberColumn(label, format="localized")
        else:
            cfg[col] = st.column_config.NumberColumn(label, format="%.2f")
    return cfg


# ---------------------------------------------------------------------------
# Gráfico automático del asistente
# ---------------------------------------------------------------------------

_DATE_HINT = ("mes", "fecha", "date", "month", "periodo", "anio", "año", "year", "dia")
_MONEY_HINT = ("ingreso", "monto", "valor", "precio", "ticket", "neto", "bruto", "cedido", "venta", "importe")


def auto_chart(df: pd.DataFrame) -> go.Figure | None:
    """1 categoría + 1 número -> barras; mes/fecha + número -> línea; en otro caso, ninguno."""
    if df is None or df.empty or df.shape[1] != 2 or len(df) < 2:
        return None
    a, b = df.columns
    num_cols = [c for c in (a, b) if pd.api.types.is_numeric_dtype(df[c])]
    if len(num_cols) != 1:
        return None
    value = num_cols[0]
    label = b if value == a else a
    money = any(h in str(value).lower() for h in _MONEY_HINT)
    title = str(value).replace("_", " ").capitalize()
    if any(h in str(label).lower() for h in _DATE_HINT):
        d = df.sort_values(label)
        return line(d, label, value, money=money, y_title=title)
    if len(df) > 25:
        return None
    return hbar(df, label, value, money=money, value_title=title)
