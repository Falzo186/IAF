"""Pruebas del arnés de evaluación: el comparador acepta SQL equivalente y rechaza la incorrecta."""

import pandas as pd
import pytest

import eval_text2sql as ev
import sql_engine as se

ITEMS = {it["id"]: it for it in ev.load_golden()}


def run(sql):
    return se.execute_sql(se.validate_sql(sql))


def ref(item_id):
    return run(ITEMS[item_id]["sql"])


def test_golden_has_ten_per_level_and_valid_checks():
    levels = [it["nivel"] for it in ITEMS.values()]
    assert levels.count("basico") == 10 and levels.count("negocio") == 10
    for it in ITEMS.values():
        df = ref(it["id"])
        assert not df.empty, it["id"]
        for col in it["check"].get("key_columns", []):
            assert col in df.columns, (it["id"], col)


def test_business_questions_do_not_copy_router_keywords_verbatim():
    """Las preguntas de negocio se enrutan, pero no son una de las formulaciones de prueba."""
    from tests.test_sql_engine import ROUTING_CASES
    phrasings = {q for qs in ROUTING_CASES.values() for q in qs}
    for it in ITEMS.values():
        if it["nivel"] == "negocio":
            assert it["pregunta"] not in phrasings
            assert se.match_business_query(it["pregunta"]).id == it["business_query"]


@pytest.mark.parametrize("item_id, equivalent_sql", [
    # Otra vista / otra agregación con el mismo resultado
    ("B2", "SELECT SUM(net_total) FROM v_orders WHERE order_status = 4 AND order_date LIKE '2017%'"),
    # Columnas en otro orden y con otros alias
    ("B6", "SELECT SUM(net_amount) AS total, category_name AS cat FROM v_order_lines "
           "WHERE order_status = 4 GROUP BY cat"),
    # Columnas extra no afectan a las columnas clave
    ("B3", "SELECT product_name, SUM(quantity) AS u, COUNT(*) AS lineas FROM v_order_lines "
           "WHERE order_status = 4 GROUP BY product_name ORDER BY u DESC LIMIT 5"),
    # Subconjunto: basta con que aparezca el total perdido
    ("N10", "SELECT SUM(net_total) AS perdido FROM v_orders WHERE order_status = 3"),
])
def test_equivalent_sql_is_accepted(item_id, equivalent_sql):
    ok, reason = ev.compare_results(ref(item_id), run(equivalent_sql), ITEMS[item_id]["check"])
    assert ok, reason


@pytest.mark.parametrize("item_id, wrong_sql", [
    # Olvida filtrar ventas completadas
    ("B2", "SELECT ROUND(SUM(net_amount), 2) FROM v_order_lines WHERE strftime('%Y', order_date) = '2017'"),
    # Recalcula sin descuento (bruto en vez de neto)
    ("B6", "SELECT category_name, SUM(list_price * quantity) FROM v_order_lines "
           "WHERE order_status = 4 GROUP BY category_name"),
    # Devuelve más filas de las pedidas
    ("B3", "SELECT product_name, SUM(quantity) AS u FROM v_order_lines WHERE order_status = 4 "
           "GROUP BY product_name ORDER BY u DESC LIMIT 10"),
    # Estado equivocado (pendientes en vez de rechazadas)
    ("N10", "SELECT SUM(net_total) FROM v_orders WHERE order_status = 1"),
    # Umbral de stock distinto
    ("N2", "SELECT product_name AS producto, 'x' AS tienda FROM products LIMIT 14"),
])
def test_wrong_sql_is_rejected(item_id, wrong_sql):
    ok, _ = ev.compare_results(ref(item_id), run(wrong_sql), ITEMS[item_id]["check"])
    assert not ok


def test_compare_handles_missing_result():
    ok, reason = ev.compare_results(pd.DataFrame({"a": [1]}), None, {"mode": "exact"})
    assert not ok and reason == "sin resultado"


def test_oracle_run_scores_everything(tmp_path):
    results = ev.evaluate(["oraculo"], ["llm", "full"], ev.LEVELS, list(ITEMS.values()),
                          lambda _m: ev.oracle_llm(list(ITEMS.values())))
    assert all(r["ok"] for r in results)
    full_biz = [r for r in results if r["modo"] == "full" and r["nivel"] == "negocio"]
    assert all(r["fuente"] == "verificada" for r in full_biz)
    report = ev.build_report(results, ["oraculo"], ["llm", "full"], {}, "t")
    assert "| oraculo | solo LLM | 10/10 | 10/10 |" in report
