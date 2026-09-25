"""Pruebas de sql_engine sin Ollama: el LLM se sustituye por un falso."""

import io
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

import config
import database_builder
import sql_engine as se
from business_queries import BUSINESS_QUERIES, BY_ID, render_sql, run_business_query


@pytest.fixture(scope="module", autouse=True)
def database():
    """Garantiza que exista bikestores.db (no reconstruye si está al día)."""
    database_builder.build_database()
    return config.DB_PATH


class FakeLLM:
    """LLM falso: devuelve las respuestas en orden y registra cada llamada."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, model, messages, **options):
        self.calls.append({"model": model, "messages": messages, "options": options})
        item = self.responses.pop(0) if self.responses else "Resumen ejecutivo."
        if isinstance(item, Exception):
            raise item
        return item


def fenced(sql):
    return f"```sql\n{sql}\n```"


# --- extract_sql -------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("<think>Debo sumar net_amount... SELECT mal</think>\n```sql\nSELECT 1\n```", "SELECT 1"),
    ("```sql\nSELECT a FROM b\n```", "SELECT a FROM b"),
    ("```\nSELECT a FROM b\n```", "SELECT a FROM b"),
    ("Claro, aquí tienes:\n```sql\nSELECT a FROM b\n```\nEsta consulta suma todo.", "SELECT a FROM b"),
    ("Aquí está: SELECT a FROM b; Esta consulta devuelve a.", "SELECT a FROM b"),
    ("SELECT a FROM b;", "SELECT a FROM b"),
    ("```sql\nSELECT a -- comentario\nFROM b /* otro */;\n```", "SELECT a \nFROM b"),
    ("WITH x AS (SELECT 1) SELECT * FROM x", "WITH x AS (SELECT 1) SELECT * FROM x"),
    ("No sé responder eso.", ""),
])
def test_extract_sql(text, expected):
    assert se.extract_sql(text).strip() == expected.strip()


# --- validate_sql ------------------------------------------------------------

@pytest.mark.parametrize("sql, fragment", [
    ("DELETE FROM orders", "DELETE"),
    ("SELECT 1; SELECT 2", "1 sentencia"),
    ("SELECT * FROM orders; DROP TABLE orders", "DROP"),
    ("PRAGMA table_info(orders)", "PRAGMA"),
    ("SELECT * FROM tabla_inexistente", "no existe"),
    ("WITH x AS (SELECT 1) INSERT INTO brands VALUES (99, 'x')", "INSERT"),
    ("REPLACE INTO brands VALUES (1, 'x')", "REPLACE"),
    ("ATTACH DATABASE 'otra.db' AS o", "ATTACH"),
    ("SELECT * FROM otra.orders", "otra base"),
    ("", "ninguna consulta"),
])
def test_validate_rejects(sql, fragment):
    with pytest.raises(se.SQLValidationError, match=fragment):
        se.validate_sql(sql)


def test_validate_accepts_with_and_adds_limit():
    sql = "WITH t AS (SELECT store_id, SUM(net_total) AS x FROM v_orders GROUP BY store_id) SELECT * FROM t"
    out = se.validate_sql(sql)
    assert out.endswith("LIMIT 500")
    assert len(se.execute_sql(out)) == 3


def test_validate_keeps_existing_limit_and_allows_replace_function():
    out = se.validate_sql("SELECT replace(brand_name, 'e', 'E') FROM brands LIMIT 3")
    assert out.count("LIMIT") == 1


def test_keywords_inside_strings_are_not_rejected():
    out = se.validate_sql("SELECT COUNT(*) FROM products WHERE product_name LIKE '%delete%'")
    assert "LIMIT 500" in out


# --- Ejecución segura --------------------------------------------------------

def test_readonly_connection_rejects_writes():
    conn = se._ro_connect(config.DB_PATH)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM brands")
    finally:
        conn.close()
    with pytest.raises(Exception):
        se.execute_sql("UPDATE brands SET brand_name = 'x'")


def test_heavy_query_is_interrupted():
    sql = se.validate_sql(
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT COUNT(*) FROM c"
    )
    with pytest.raises(se.QueryTimeout):
        se.execute_sql(sql, timeout=0.5)


# --- Contexto y prompt -------------------------------------------------------

def test_schema_context_size():
    ctx = se.get_schema_context()
    tokens = se.estimate_tokens(ctx)
    print(f"\nContexto de esquema: {len(ctx)} caracteres, ~{tokens} tokens")
    assert tokens < 1200
    assert ctx.index("v_order_lines(") < ctx.index("products(")
    for omitted in ("order_items(", "orders(", "order_status_lookup(", "db_metadata("):
        assert omitted not in ctx.replace("v_orders(", "")
    for value in ("Electric Bikes", "Baldwin Bikes", "Trek", "Rechazada", "TX", "2018-12-28", "2018-03-31"):
        assert value in ctx


@pytest.mark.parametrize("question, sql", se.FEW_SHOTS)
def test_few_shot_examples_execute(question, sql):
    df = se.execute_sql(se.validate_sql(sql))
    assert not df.empty, question


def test_history_is_limited_to_two_turns():
    history = [{"question": f"p{i}", "sql": f"SELECT {i}"} for i in range(5)]
    msgs = se.build_sql_messages("¿y en 2017?", history)
    contents = [m["content"] for m in msgs[1:]]
    assert contents[0] == "p3" and "SELECT 4" in contents[3] and contents[-1] == "¿y en 2017?"
    assert len(msgs) == 1 + 4 + 1


# --- Bucle con reintento -----------------------------------------------------

GOOD_SQL = "SELECT store_name AS tienda, COUNT(*) AS ordenes FROM v_orders GROUP BY store_name"


def test_retry_fixes_broken_sql():
    llm = FakeLLM(fenced("SELECT columna_rota FROM v_orders"), fenced(GOOD_SQL), "Resumen.")
    r = se.answer_question("¿Cuántas órdenes tiene cada tienda?", "falso", llm=llm)
    assert r.error is None
    assert r.attempts == 2
    assert r.source == "llm"
    assert len(r.df) == 3 and r.df["ordenes"].sum() == 1615
    retry_prompt = llm.calls[1]["messages"][-1]["content"]
    assert "columna_rota" in retry_prompt
    assert llm.calls[0]["options"] == {"temperature": 0.0, "num_predict": 400}


def test_two_failures_return_friendly_error():
    llm = FakeLLM(fenced("SELECT x FROM nada"), fenced("DELETE FROM orders"))
    r = se.answer_question("¿Algo imposible?", "falso", llm=llm)
    assert r.attempts == 2
    assert r.error and r.df is None
    assert r.answer == se.FRIENDLY_ERROR
    assert len(llm.calls) == 2


def test_llm_unavailable_does_not_raise():
    import ollama_manager
    llm = FakeLLM(ollama_manager.OllamaUnavailable("Ollama no responde"))
    r = se.answer_question("¿Cuántos clientes hay?", "falso", llm=llm)
    assert r.error == "Ollama no responde"
    assert "Ollama" in r.answer


def test_single_value_skips_second_llm_call():
    llm = FakeLLM(fenced("SELECT ROUND(SUM(net_total), 2) AS ingreso_neto FROM v_orders WHERE order_status = 4"))
    r = se.answer_question("¿Cuánto vendimos?", "falso", llm=llm)
    assert len(llm.calls) == 1
    assert r.answer.startswith("El resultado (ingreso neto) es $")


def test_zero_rows_answer_without_llm():
    llm = FakeLLM(fenced("SELECT * FROM v_orders WHERE order_id = -1"))
    r = se.answer_question("¿Orden -1?", "falso", llm=llm)
    assert len(llm.calls) == 1
    assert r.answer == se.NO_ROWS_ANSWER


def test_synthesis_call_and_fallback():
    llm = FakeLLM(fenced(GOOD_SQL), "Baldwin Bikes concentra la mayoría de las órdenes.")
    r = se.answer_question("Órdenes por tienda", "falso", llm=llm)
    assert r.answer == "Baldwin Bikes concentra la mayoría de las órdenes."
    synth = llm.calls[1]
    assert synth["options"] == {"temperature": 0.3, "num_predict": 250}
    assert "3 filas en total" in synth["messages"][1]["content"]

    llm = FakeLLM(fenced(GOOD_SQL), RuntimeError("se cayó"))
    r = se.answer_question("Órdenes por tienda", "falso", llm=llm)
    assert r.error is None and r.df is not None and "3 fila" in r.answer


# --- Enrutador ---------------------------------------------------------------

ROUTING_CASES = {
    "N1": ["¿Qué productos nos cuestan más en descuentos?",
           "Rentabilidad de los descuentos por producto",
           "¿Cuánto margen perdemos por descuentos?"],
    "N2": ["¿Hay riesgo de quiebre de stock en los productos populares?",
           "Productos más vendidos con poco stock",
           "¿Qué artículos con alta demanda se están quedando sin existencias?"],
    "N3": ["Ranking de vendedores en Electric Bikes",
           "¿Qué empleado vende más bicicletas eléctricas?",
           "Productividad del personal en la categoría de bicis eléctricas"],
    "N4": ["Ciudades con clientes premium",
           "¿Dónde se vende con el descuento mínimo?",
           "Perfil geográfico de las compras con menos descuento"],
    "N5": ["¿Cuántas órdenes llegaron con retraso y cuánto dinero representan?",
           "Ineficiencia logística por tienda",
           "Pedidos entregados tarde por sucursal"],
    "N6": ["Inventario inactivo de los últimos 6 meses",
           "¿Qué productos no se han vendido en seis meses y siguen en stock?",
           "Capital inmovilizado en stock sin rotación"],
    "N7": ["Clientes que compran varias marcas en la misma orden",
           "¿Qué compradores mezclan distintas marcas?",
           "Diversificación de marcas por cliente"],
    "N8": ["Ticket promedio por tienda",
           "¿Cuál es el valor medio de una orden en cada sucursal?",
           "Compra promedio por local"],
    "N9": ["Rotación mensual por categoría",
           "¿Qué marcas se venden más lento?",
           "Eficiencia del catálogo por marca"],
    "N10": ["Monto perdido por órdenes rechazadas",
            "¿Cuántos pedidos se cancelaron por mes?",
            "Ventas caídas por tienda"],
}

OFF_TOPIC = [
    "¿Cuántos clientes hay en NY?",
    "¿Cuál fue el ingreso neto de 2017?",
    "Top 5 productos más vendidos",
    "¿Cuántas tiendas tiene la empresa?",
    "Lista las categorías de productos",
    "¿Cuántas órdenes hay en cada estatus (Pendiente, En proceso, Rechazada, Completada)?",
]


@pytest.mark.parametrize("expected, question",
                         [(bid, q) for bid, qs in ROUTING_CASES.items() for q in qs])
def test_router_matches(expected, question):
    bq = se.match_business_query(question)
    assert bq is not None and bq.id == expected, question


@pytest.mark.parametrize("question", OFF_TOPIC)
def test_router_ignores_off_topic(question):
    assert se.match_business_query(question) is None


def test_routed_question_uses_verified_sql():
    llm = FakeLLM("Resumen de retrasos.")
    r = se.answer_question("Pedidos entregados tarde por sucursal", "falso", llm=llm)
    assert r.source == "verificada" and r.business_query_id == "N5"
    assert r.attempts == 0 and len(llm.calls) == 0  # config.VERIFIED_SYNTHESIS = False: sin LLM
    assert r.df.iloc[-1]["tienda"] == "Total"
    assert r.answer.startswith("458 órdenes")        # frase determinística de analytics.insight


def test_verified_synthesis_option_calls_llm_once():
    llm = FakeLLM("Resumen de retrasos.")
    r = se.answer_question("Pedidos entregados tarde por sucursal", "falso", llm=llm,
                           verified_synthesis=True)
    assert r.answer == "Resumen de retrasos." and len(llm.calls) == 1
    user_msg = llm.calls[0]["messages"][1]["content"]
    assert "Hallazgo principal (ya calculado" in user_msg and "458 órdenes" in user_msg


def test_router_can_be_disabled():
    llm = FakeLLM(fenced(GOOD_SQL), "ok")
    r = se.answer_question("Pedidos entregados tarde por sucursal", "falso", llm=llm, use_router=False)
    assert r.source == "llm"


@pytest.mark.parametrize("bq", BUSINESS_QUERIES, ids=lambda q: q.id)
def test_business_queries_execute(bq):
    df = se.execute_sql(se.validate_sql(render_sql(bq)))
    assert not df.empty
    assert bq.definicion and bq.titulo


# --- Filtros y rutas (Fase 2B) -------------------------------------------------

Y2017 = {"date_from": "2017-01-01", "date_to": "2017-12-31"}
SUPPORTED_FILTER_CASES = [
    ("Ticket promedio por tienda en 2017", "N8", Y2017),
    ("¿Cuántas órdenes llegaron tarde en Baldwin?", "N5", {"store_name": "Baldwin Bikes"}),
    ("Riesgo de quiebre de stock en Santa Cruz", "N2", {"store_name": "Santa Cruz Bikes"}),
    ("Inventario inactivo en Rowlett", "N6", {"store_name": "Rowlett Bikes"}),
    ("Monto perdido por órdenes rechazadas en marzo de 2017", "N10",
     {"date_from": "2017-03-01", "date_to": "2017-03-31"}),
    ("Rentabilidad de los descuentos por producto entre 2016 y 2017", "N1",
     {"date_from": "2016-01-01", "date_to": "2017-12-31"}),
    ("Ranking de vendedores en Electric Bikes durante 2018", "N3",
     {"date_from": "2018-01-01", "date_to": "2018-12-31"}),
    ("Ciudades con clientes premium en 2016", "N4", {"date_from": "2016-01-01", "date_to": "2016-12-31"}),
    ("Clientes que compran varias marcas en la misma orden en Baldwin Bikes", "N7",
     {"store_name": "Baldwin Bikes"}),
    ("Rotación mensual por categoría en Santa Cruz en 2017", "N9", {"store_name": "Santa Cruz Bikes", **Y2017}),
]
UNSUPPORTED_FILTER_CASES = [
    ("Ticket promedio por tienda solo en Electric Bikes", "N8", "categoria"),
    ("Pedidos entregados tarde por sucursal en Texas", "N5", "estado"),
    ("¿Qué productos Trek nos cuestan más en descuentos?", "N1", "marca"),
    ("Top 3 vendedores de bicicletas eléctricas", "N3", "top-N"),
    ("Monto perdido por órdenes rechazadas en Houston", "N10", "ciudad"),
    ("¿Cuántos pedidos se cancelaron en Baldwin y Rowlett?", "N10", "varias tiendas"),
]


@pytest.mark.parametrize("question, bq_id, params", SUPPORTED_FILTER_CASES)
def test_route_verified_with_supported_filters(question, bq_id, params):
    route, bq, applied, unsupported = se.plan_route(question)
    assert (route, bq.id, applied, unsupported) == ("verificada", bq_id, params, [])


@pytest.mark.parametrize("question, bq_id, kind", UNSUPPORTED_FILTER_CASES)
def test_route_anchored_with_unsupported_filters(question, bq_id, kind):
    route, bq, _, unsupported = se.plan_route(question)
    assert route == "llm_anclada" and bq.id == bq_id
    assert kind in [u[0] for u in unsupported]


@pytest.mark.parametrize("expected, question",
                         [(bid, q) for bid, qs in ROUTING_CASES.items() for q in qs])
def test_existing_phrasings_stay_verified_without_filters(expected, question):
    assert se.plan_route(question)[:3] == ("verificada", BY_ID[expected], {})


@pytest.mark.parametrize("question", OFF_TOPIC)
def test_off_topic_goes_to_plain_llm(question):
    assert se.plan_route(question)[0] == "llm"


def test_verified_answer_applies_filters():
    llm = FakeLLM("Resumen.")
    r = se.answer_question("Ticket promedio por tienda en 2017", "falso", llm=llm)
    assert r.source == "verificada" and r.filters == Y2017
    assert "order_date >= '2017-01-01'" in r.sql and ":date_from" not in r.sql
    full = run_business_query("N8")
    assert r.df["ordenes"].sum() < full["ordenes"].sum()


def test_anchored_route_injects_reference_sql():
    llm = FakeLLM(fenced("SELECT store_name AS tienda, ROUND(AVG(net_total), 2) AS ticket FROM v_orders "
                         "WHERE order_status = 4 GROUP BY store_name"), "Resumen.")
    r = se.answer_question("Ticket promedio por tienda solo en Electric Bikes", "falso", llm=llm)
    assert r.source == "llm_anclada" and r.business_query_id == "N8"
    assert ("categoria", "Electric Bikes") in r.unsupported_filters
    system = llm.calls[0]["messages"][0]["content"]
    assert "Consulta de referencia para esta necesidad (Ticket promedio por tienda)" in system
    assert "AVG(net_total)" in system and ":store_name" not in system


def test_verified_query_works_without_llm():
    import ollama_manager
    llm = FakeLLM(ollama_manager.OllamaUnavailable("apagado"))
    r = se.answer_question("Pedidos entregados tarde por sucursal", "falso", llm=llm)
    assert r.error is None and r.source == "verificada" and not r.df.empty
    assert r.answer and "apagado" not in r.answer


@pytest.mark.parametrize("bq", BUSINESS_QUERIES, ids=lambda q: q.id)
def test_null_parameters_reproduce_phase2_baseline(bq):
    """Regresión: con todos los filtros en NULL las cifras de fase2.md quedan idénticas."""
    baseline = pd.read_csv(Path(__file__).parent / "fixtures" / "bq_baseline" / f"{bq.id}.csv")
    current = run_business_query(bq)[list(baseline.columns)]
    current = pd.read_csv(io.StringIO(current.to_csv(index=False)))
    pd.testing.assert_frame_equal(current, baseline)


@pytest.mark.parametrize("bq", BUSINESS_QUERIES, ids=lambda q: q.id)
def test_rendered_sql_matches_parametrized_execution(bq):
    params = {"store_name": "Baldwin Bikes", **Y2017}
    assert se.execute_sql(render_sql(bq, **params)).equals(run_business_query(bq, **params))


def test_n6_inventory_status():
    df = run_business_query("N6")
    assert set(df["estado_inventario"]) == {"Nunca vendido"}      # ventana por defecto
    assert len(df) == 29 and df["unidades_inmovilizadas"].sum() == 1234
    short = run_business_query("N6", date_from="2018-01-01", date_to="2018-03-31")
    assert set(short["estado_inventario"]) == {"Nunca vendido", "Sin ventas recientes"}


def test_extract_filters_details():
    f = se.extract_filters("¿Cuánto vendió Marcelene en Baldwin entre marzo de 2017 y junio de 2017?")
    assert f["store_name"] == "Baldwin Bikes"
    assert (f["date_from"], f["date_to"]) == ("2017-03-01", "2017-06-30")
    assert ("vendedor", "Marcelene Boyer") in f["unsupported"]
    f = se.extract_filters("Compara 2016 vs 2017")
    assert f["date_from"] is None and f["unsupported"][0][0] == "comparación de periodos"
    assert se.extract_filters("inventario de los últimos 6 meses")["top_n"] is None
    assert se.extract_filters("dejando dinero sobre la mesa")["unsupported"] == []


def test_format_value():
    assert se.format_value(1234.5, "ingreso_neto") == "$1,234.50"
    assert se.format_value(32.04, "pct_tarde") == "32.04%"
    assert se.format_value(1615, "ordenes") == "1,615"
