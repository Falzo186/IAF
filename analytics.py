"""Métricas del dashboard (sin Streamlit). Todas las lecturas son de solo lectura.

Las 10 necesidades se obtienen con la misma SQL verificada que usa el chat
(business_queries.run_business_query), sin el límite de filas del chat.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import config
import db
from business_queries import BY_ID, build_params, run_business_query

MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


# ---------------------------------------------------------------------------
# Periodos
# ---------------------------------------------------------------------------

def default_period(db_path: Path = config.DB_PATH) -> tuple[date, date]:
    """Periodo con ventas completadas: min_order_date -> last_completed_date."""
    meta = db.metadata(db_path)
    return date.fromisoformat(meta["min_order_date"]), date.fromisoformat(meta["last_completed_date"])


def month_label(d: date) -> str:
    return f"{MONTHS_ES[d.month - 1]} {d.year}"


def previous_period(date_from: date, date_to: date) -> tuple[date, date]:
    """Periodo inmediatamente anterior de igual duración (en días, ambos extremos inclusive)."""
    days = (date_to - date_from).days + 1
    prev_to = date_from - timedelta(days=1)
    return prev_to - timedelta(days=days - 1), prev_to


def _as_date(value) -> date | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

KPI_SQL = """
SELECT
    SUM(CASE WHEN order_status = 4 THEN net_total END)          AS ingreso_neto,
    SUM(CASE WHEN order_status = 4 THEN 1 ELSE 0 END)           AS ordenes,
    AVG(CASE WHEN order_status = 4 THEN net_total END)          AS ticket_promedio,
    100.0 * SUM(CASE WHEN order_status = 4 THEN discount_total END)
          / SUM(CASE WHEN order_status = 4 THEN gross_total END) AS pct_descuento,
    100.0 * SUM(is_late) / NULLIF(SUM(is_shipped), 0)           AS pct_tarde,
    COALESCE(SUM(CASE WHEN order_status = 3 THEN net_total END), 0) AS ingreso_perdido
FROM v_orders
WHERE (:store_name IS NULL OR store_name = :store_name)
  AND (:date_from IS NULL OR order_date >= :date_from)
  AND (:date_to IS NULL OR order_date <= :date_to)
"""

KPI_META = {
    # clave: (etiqueta, formato, tipo de delta, ¿subir es bueno?)
    "ingreso_neto": ("Ingreso neto", "money", "pct", True),
    "ordenes": ("Órdenes completadas", "int", "pct", True),
    "ticket_promedio": ("Ticket promedio", "money", "pct", True),
    "pct_descuento": ("Descuento cedido", "pct", "pp", False),
    "pct_tarde": ("Envíos tarde", "pct", "pp", False),
    "ingreso_perdido": ("Perdido por rechazos", "money", "pct", False),
}


def _kpi_values(store_name, date_from, date_to, db_path) -> dict:
    row = db.run_query(KPI_SQL, build_params(store_name, date_from, date_to), db_path).iloc[0]
    return {k: (None if pd.isna(row[k]) else float(row[k])) for k in KPI_META}


def get_kpis(store_name: str | None = None, date_from=None, date_to=None,
             db_path: Path = config.DB_PATH) -> dict:
    """KPIs del periodo con su variación contra el periodo anterior de igual duración.

    Cada entrada: {label, value, fmt, delta, delta_kind ('pct' | 'pp'), higher_is_better}.
    delta es None si el periodo anterior queda fuera de los datos o si su valor es 0/nulo.
    """
    d_from, d_to = default_period(db_path)
    date_from, date_to = _as_date(date_from) or d_from, _as_date(date_to) or d_to
    current = _kpi_values(store_name, date_from, date_to, db_path)

    min_date = date.fromisoformat(db.metadata(db_path)["min_order_date"])
    prev_from, prev_to = previous_period(date_from, date_to)
    previous = _kpi_values(store_name, prev_from, prev_to, db_path) if prev_from >= min_date else {}

    out = {}
    for key, (label, fmt, kind, higher_is_better) in KPI_META.items():
        value, before = current[key], previous.get(key)
        delta = None
        if value is not None and before not in (None, 0):
            delta = (value - before) if kind == "pp" else 100.0 * (value - before) / abs(before)
        out[key] = {"label": label, "value": value, "fmt": fmt, "delta": delta,
                    "delta_kind": kind, "higher_is_better": higher_is_better}
    out["_periodo"] = {"actual": (date_from, date_to),
                       "anterior": (prev_from, prev_to) if previous else None}
    return out


def monthly_revenue(store_name: str | None = None, date_from=None, date_to=None,
                    db_path: Path = config.DB_PATH) -> pd.DataFrame:
    """Ingreso neto y órdenes completadas por mes."""
    sql = """
    SELECT strftime('%Y-%m', order_date) AS mes,
           ROUND(SUM(net_total), 2) AS ingreso_neto,
           COUNT(*) AS ordenes
    FROM v_orders
    WHERE order_status = 4
      AND (:store_name IS NULL OR store_name = :store_name)
      AND (:date_from IS NULL OR order_date >= :date_from)
      AND (:date_to IS NULL OR order_date <= :date_to)
    GROUP BY mes ORDER BY mes"""
    return db.run_query(sql, build_params(store_name, date_from, date_to), db_path)


def need(n: str | int, store_name: str | None = None, date_from=None, date_to=None,
         db_path: Path = config.DB_PATH) -> pd.DataFrame:
    """Resultado completo (sin límite de filas) de una necesidad verificada: la misma SQL del chat."""
    bq_id = n if isinstance(n, str) else f"N{n}"
    return run_business_query(BY_ID[bq_id], store_name, date_from, date_to, limit=None, db_path=db_path)


# ---------------------------------------------------------------------------
# Insights determinísticos
# ---------------------------------------------------------------------------

def money(x: float) -> str:
    return f"${x:,.2f}"


def _insight_n1(df):
    top = df[df["ranking"] == "Top ingreso neto"]
    worst = df[df["ranking"] == "Top % cedido"]
    first = top.iloc[0]
    return (f"{first['producto']} lidera el ingreso con descuento ({money(first['ingreso_neto'])}); "
            f"los 10 productos de mayor ingreso cedieron {money(top['descuento_cedido'].sum())} en "
            f"descuentos y el mayor % cedido llega a {worst['pct_cedido'].max():.1f}%.")


def _insight_n2(df):
    products = df["producto"].nunique()
    zero = int((df["stock"] == 0).sum())
    return (f"{products} productos top están bajo 5 unidades en alguna tienda "
            f"({len(df)} casos); {zero} ya en cero.")


def _insight_n3(df):
    first = df.iloc[0]
    share = 100.0 * first["ingreso_neto"] / df["ingreso_neto"].sum()
    return (f"{first['vendedor']} ({first['tienda']}) lidera Electric Bikes con "
            f"{money(first['ingreso_neto'])}, el {share:.0f}% del ingreso de la categoría.")


def _insight_n4(df):
    first = df.iloc[0]                                              # mayor monto
    share = df.sort_values("pct_ingreso_desc_minimo", ascending=False).iloc[0]  # mayor proporción
    state = df["estado"].value_counts()
    return (f"{share['ciudad']}, {share['estado']} tiene la mayor proporción de ingreso con descuento "
            f"mínimo ({share['pct_ingreso_desc_minimo']:.1f}%); {first['ciudad']} lidera en monto "
            f"({money(first['ingreso_neto_desc_minimo'])}). {state.iloc[0]} de las {len(df)} ciudades "
            f"están en {state.index[0]}.")


def _insight_n5(df):
    total = df[df["tienda"] == "Total"].iloc[0]
    stores = df[df["tienda"] != "Total"]
    if not total["ordenes_tarde"]:
        return "No hubo órdenes entregadas tarde en el periodo."
    top = stores.sort_values("monto_neto", ascending=False).iloc[0]
    share = 100.0 * top["monto_neto"] / total["monto_neto"]
    return (f"{int(total['ordenes_tarde']):,} órdenes por {money(total['monto_neto'])} se entregaron "
            f"tarde (retraso promedio {total['dias_retraso_prom']:.1f} días); {top['tienda']} "
            f"concentra el {share:.0f}% de ese valor.")


def _insight_n6(df):
    never = int((df["estado_inventario"] == "Nunca vendido").sum())
    return (f"{len(df)} productos sin ventas recientes inmovilizan "
            f"{int(df['unidades_inmovilizadas'].sum()):,} unidades por "
            f"{money(df['valor_inmovilizado'].sum())}; {never} nunca se han vendido.")


def _insight_n7(df):
    top = int(df["max_marcas"].max())
    return (f"{len(df):,} clientes combinaron 2 o más marcas en una orden; "
            f"{int((df['max_marcas'] == top).sum())} llegaron a {top} marcas.")


def _insight_n8(df):
    hi, lo = df.iloc[0], df.iloc[-1]
    if len(df) == 1:
        return f"{hi['tienda']} tiene un ticket promedio de {money(hi['ticket_promedio'])} en {int(hi['ordenes']):,} órdenes."
    return (f"{hi['tienda']} tiene el ticket promedio más alto ({money(hi['ticket_promedio'])}) "
            f"frente a {money(lo['ticket_promedio'])} de {lo['tienda']}.")


def _insight_n9(df):
    cat = df[df["dimension"] == "Categoría"].sort_values("rotacion_mensual").iloc[0]
    brand = df[df["dimension"] == "Marca"].sort_values("rotacion_mensual").iloc[0]
    return (f"La categoría más lenta es {cat['nombre']} ({cat['rotacion_mensual']:.1f} u./mes) y la "
            f"marca más lenta, {brand['nombre']} ({brand['rotacion_mensual']:.1f} u./mes).")


def _insight_n10(df):
    total = df[df["nivel"] == "Total"].iloc[0]
    if not total["ordenes"]:
        return "No hubo órdenes rechazadas en el periodo."
    stores = df[df["nivel"] == "Tienda"].sort_values("monto_neto_perdido", ascending=False)
    top = stores.iloc[0]
    return (f"{int(total['ordenes'])} órdenes rechazadas representan {money(total['monto_neto_perdido'])} "
            f"perdidos; {top['detalle']} acumula el mayor monto ({money(top['monto_neto_perdido'])}).")


_INSIGHTS = {"N1": _insight_n1, "N2": _insight_n2, "N3": _insight_n3, "N4": _insight_n4,
             "N5": _insight_n5, "N6": _insight_n6, "N7": _insight_n7, "N8": _insight_n8,
             "N9": _insight_n9, "N10": _insight_n10}


def insight(n: str | int, df: pd.DataFrame) -> str:
    """Frase determinística (sin LLM) con la cifra principal de la necesidad."""
    bq_id = n if isinstance(n, str) else f"N{n}"
    if df is None or df.empty:
        return "Sin datos para los filtros seleccionados."
    try:
        return _INSIGHTS[bq_id](df)
    except (KeyError, IndexError, ZeroDivisionError):
        return f"La consulta devolvió {len(df):,} fila(s)."
