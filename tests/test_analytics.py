"""Pruebas de analytics: KPIs contra las cifras de fase2.md, necesidades, filtros y periodos."""

from datetime import date

import pytest

import analytics as an
import db


def test_default_period_from_metadata():
    assert an.default_period() == (date(2016, 1, 1), date(2018, 3, 31))
    assert an.month_label(date(2018, 3, 31)) == "mar 2018"


def test_kpis_with_null_filters_match_phase2_figures():
    k = an.get_kpis()
    # fase2.md §4.2: bruto $7,438,010.06 - cedido $775,394.82 = neto completado
    assert k["ingreso_neto"]["value"] == pytest.approx(7_438_010.06 - 775_394.82, abs=0.01)
    assert k["ordenes"]["value"] == 1445
    assert k["pct_descuento"]["value"] == pytest.approx(100 * 775_394.82 / 7_438_010.06, abs=0.01)
    assert k["pct_tarde"]["value"] == pytest.approx(100 * 458 / 1445, abs=0.01)  # N5: 458 órdenes tarde
    assert k["ticket_promedio"]["value"] == pytest.approx(6_662_615.24 / 1445, abs=0.01)
    # Rechazos dentro del periodo con ventas (N10 total $208,579.45 incluye abr–dic 2018)
    after = db.run_query("SELECT SUM(net_total) AS s FROM v_orders WHERE order_status = 3 "
                         "AND order_date > '2018-03-31'")["s"].iloc[0]
    assert k["ingreso_perdido"]["value"] == pytest.approx(208_579.45 - after, abs=0.01)
    # El periodo por defecto empieza con los datos: no hay periodo anterior comparable
    assert all(k[key]["delta"] is None for key in an.KPI_META)


def test_kpis_full_range_match_n10_total():
    k = an.get_kpis(date_from="2016-01-01", date_to="2018-12-28")
    assert k["ingreso_perdido"]["value"] == pytest.approx(208_579.45, abs=0.01)


@pytest.mark.parametrize("n", range(1, 11))
def test_each_need_returns_rows(n):
    df = an.need(n)
    assert not df.empty
    assert an.insight(n, df) and "fila(s)" not in an.insight(n, df)


def test_need_has_no_row_limit():
    assert len(an.need(7)) == 1064   # el chat lo corta en 500; el dashboard no


def test_store_filter_reduces_totals():
    all_k = an.get_kpis()
    baldwin = an.get_kpis("Baldwin Bikes")
    assert baldwin["ingreso_neto"]["value"] < all_k["ingreso_neto"]["value"]
    assert baldwin["ordenes"]["value"] < all_k["ordenes"]["value"]
    assert an.monthly_revenue("Baldwin Bikes")["ingreso_neto"].sum() < an.monthly_revenue()["ingreso_neto"].sum()
    n5 = an.need(5, store_name="Baldwin Bikes")
    assert set(n5["tienda"]) == {"Baldwin Bikes", "Total"}
    assert n5.iloc[-1]["ordenes_tarde"] == 317


def test_previous_period_same_length():
    assert an.previous_period(date(2017, 1, 1), date(2017, 12, 31)) == (date(2016, 1, 2), date(2016, 12, 31))
    assert an.previous_period(date(2017, 3, 1), date(2017, 3, 31)) == (date(2017, 1, 29), date(2017, 2, 28))


def test_kpi_delta_against_previous_period():
    k = an.get_kpis(date_from="2017-01-01", date_to="2017-12-31")
    prev = an.get_kpis(date_from="2016-01-02", date_to="2016-12-31")
    expected = 100 * (k["ingreso_neto"]["value"] - prev["ingreso_neto"]["value"]) / prev["ingreso_neto"]["value"]
    assert k["ingreso_neto"]["delta"] == pytest.approx(expected)
    assert k["pct_tarde"]["delta"] == pytest.approx(k["pct_tarde"]["value"] - prev["pct_tarde"]["value"])
    assert k["_periodo"]["anterior"] == (date(2016, 1, 2), date(2016, 12, 31))


def test_insight_examples():
    assert an.insight(2, an.need(2)) == "7 productos top están bajo 5 unidades en alguna tienda (10 casos); 3 ya en cero."
    assert an.insight(5, an.need(5, store_name="Rowlett Bikes", date_from="2016-01-01",
                                  date_to="2016-01-31")) == "No hubo órdenes entregadas tarde en el periodo."
    assert an.insight(1, an.need(1).iloc[0:0]) == "Sin datos para los filtros seleccionados."


def test_connections_are_read_only():
    conn = db.ro_connect()
    try:
        with pytest.raises(Exception):
            conn.execute("DELETE FROM brands")
    finally:
        conn.close()
