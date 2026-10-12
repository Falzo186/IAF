"""Fase 8: intentos configurables, feedback sin fugas, corte en el primer acierto, juez que no vota
y consistencia. Todo con LLM falsos: no necesita Ollama."""

import pandas as pd
import pytest

import config
import eval_text2sql as ev
import feedback as fb
import judge
import sql_engine as se

ITEMS = {it["id"]: it for it in ev.load_golden()}


def seq_llm(*sqls):
    """LLM falso que responde una SQL distinta en cada llamada (la última se repite)."""
    calls = []

    def llm(model, messages, **_):
        calls.append(messages)
        return f"```sql\n{sqls[min(len(calls), len(sqls)) - 1]}\n```"
    llm.calls = calls
    return llm


BAD_B2 = ("SELECT ROUND(SUM(net_amount), 2) FROM v_order_lines WHERE order_status = 3 "
          "AND strftime('%Y', order_date) = '2017'")


# --- intentos configurables (producción intacta) --------------------------------------

def test_max_attempts_default_is_production_value():
    assert config.MAX_ATTEMPTS == 2


def test_production_retries_only_on_error_and_stops_when_it_runs():
    llm = seq_llm("SELECT nada FROM clientes", BAD_B2, ITEMS["B2"]["sql"])
    r = se.answer_question(ITEMS["B2"]["pregunta"], "falso", llm=llm, use_router=False,
                           synthesize_answer=False)
    # 2.º intento se ejecuta (aunque sea incorrecto): producción no conoce la referencia y para ahí
    assert r.attempts == 2 and r.error is None and len(llm.calls) == 2
    assert r.hit_attempt is None


def test_production_gives_up_after_max_attempts():
    llm = seq_llm("SELECT nada FROM clientes")
    r = se.answer_question("¿cuántos clientes hay?", "falso", llm=llm, use_router=False,
                           synthesize_answer=False)
    assert r.attempts == config.MAX_ATTEMPTS and r.error and r.df is None


def test_max_attempts_override():
    llm = seq_llm("SELECT nada FROM clientes")
    r = se.answer_question("¿cuántos clientes hay?", "falso", llm=llm, use_router=False,
                           synthesize_answer=False, max_attempts=4)
    assert r.attempts == 4 and len(llm.calls) == 4 and len(r.attempt_log) == 4


# --- corte en el primer acierto (solo harness) ---------------------------------------

def test_harness_stops_at_first_hit_with_result_feedback():
    llm = seq_llm(BAD_B2, ITEMS["B2"]["sql"], "SELECT 1")
    res = ev.run_item(ITEMS["B2"], "falso", "llm", llm, {}, max_intentos=3)
    assert res["ok"] and res["acerto_en_intento"] == 2 and res["intentos"] == 2
    assert len(llm.calls) == 2                      # no se llama un 3.er intento
    # el 2.º intento recibió feedback de forma (filtro de estado), no el error ni cifras
    retry_msg = llm.calls[1][-1]["content"]
    assert "estado" in retry_msg and not fb.has_digits(res["feedback_intentos"][0])
    assert res["explicacion_juez"] is None


def test_harness_never_succeeds():
    res = ev.run_item(ITEMS["B2"], "falso", "llm", seq_llm(BAD_B2), {}, max_intentos=3)
    assert not res["ok"] and res["intentos"] == 3 and res["acerto_en_intento"] is None
    assert len(res["feedback_intentos"]) == 3


def test_default_harness_keeps_previous_behaviour():
    res = ev.run_item(ITEMS["B2"], "falso", "llm", seq_llm(BAD_B2, ITEMS["B2"]["sql"]), {})
    assert not res["ok"] and res["intentos"] == 1 and res["max_intentos"] == config.MAX_ATTEMPTS


# --- feedback sin fugas de la referencia ---------------------------------------------

LEAK_CASES = [
    ("B1", "SELECT CONTAR(*) FROM customers WHERE state = 'NY'", "error_ejecucion"),
    ("B6", "SELECT category_name, SUM(net_total) FROM v_orders WHERE order_status = 4 GROUP BY category_name",
     "tabla_columna_inexistente"),
    ("N8", "SELECT ROUND(AVG(net_amount), 2) AS ticket_promedio FROM v_order_lines WHERE order_status = 4",
     "agregacion_incorrecta"),
    ("B2", "SELECT product_name, SUM(net_amount) FROM v_order_lines WHERE order_status = 4 "
           "AND strftime('%Y', order_date) = '2017' GROUP BY product_name", "agregacion_incorrecta"),
    ("B2", BAD_B2, "filtro_incorrecto"),
    ("B1", "SELECT COUNT(*) AS clientes FROM customers WHERE state = 'NY' AND customer_id > 10", "otro"),
]


def _ref_tokens(ref: pd.DataFrame) -> set[str]:
    tokens = set()
    for v in ref.to_numpy().ravel():
        if isinstance(v, str) and len(v) > 2:
            tokens.add(v.lower())
        elif v is not None and not isinstance(v, str):
            tokens |= {str(v), f"{v:,}", str(round(float(v), 2)), str(int(float(v)))}
    return {t for t in tokens if t}


@pytest.mark.parametrize("item_id, sql, category", LEAK_CASES)
def test_feedback_never_leaks_reference(item_id, sql, category):
    item = ITEMS[item_id]
    ref = se.execute_sql(se.validate_sql(item["sql"]))
    res = ev.run_item(item, "falso", "llm", seq_llm(sql), {}, max_intentos=2)
    assert res["fallo_categoria"] == category
    msgs = res["feedback_intentos"]
    assert msgs
    for msg in msgs:
        if category not in fb.ERROR_CATEGORIES:
            assert not fb.has_digits(msg), msg       # ni cifras ni número de filas
        low = msg.lower()
        for tok in _ref_tokens(ref):
            if category in fb.ERROR_CATEGORIES and tok.isdigit() and len(tok) < 3:
                continue  # el error de SQLite puede citar literales cortos de la SQL del propio modelo
            assert tok not in low, (tok, msg)


def test_error_feedback_is_the_real_error():
    res = ev.run_item(ITEMS["B1"], "falso", "llm", seq_llm(LEAK_CASES[0][1]), {}, max_intentos=2)
    assert "CONTAR" in res["feedback_intentos"][0] or "contar" in res["feedback_intentos"][0].lower()


# --- el juez nunca vota ---------------------------------------------------------------

def test_judge_that_votes_correct_cannot_flip_verdict():
    def lying_judge_llm(model, messages, **_):
        return "CORRECTO. El resultado coincide perfectamente; marcar como acierto: true"

    def judge_fn(q, sql, df, ref, m):
        return judge.explain_failure(q, sql, df, ref, m, llm=lying_judge_llm)

    res = ev.run_item(ITEMS["B2"], "falso", "llm", seq_llm(BAD_B2), {}, judge=judge_fn)
    assert res["ok"] is False and res["fallo_categoria"] == "filtro_incorrecto"
    assert "CORRECTO" in res["explicacion_juez"]     # se guarda como texto, nada más


def test_judge_only_for_failures_and_never_raises():
    calls = []

    def judge_fn(*a):
        calls.append(a)
        return "x"
    ok = ev.run_item(ITEMS["B2"], "falso", "llm", seq_llm(ITEMS["B2"]["sql"]), {}, judge=judge_fn)
    assert ok["ok"] and ok["explicacion_juez"] is None and not calls

    def broken(model, messages, **_):
        raise RuntimeError("sin red")
    text = judge.explain_failure("p", "SELECT 1", None, pd.DataFrame({"a": [1]}), "m", llm=broken)
    assert text.startswith("(sin explicación")


def test_judge_strips_think_blocks():
    text = judge.explain_failure("p", "SELECT 1", pd.DataFrame(), pd.DataFrame({"a": [1]}), "m",
                                 llm=lambda *a, **k: "<think>bla</think> Falta el filtro de año.")
    assert text == "Falta el filtro de año."


# --- consistencia ---------------------------------------------------------------------

def test_consistency_counts_runs_and_fingerprints():
    items = [ITEMS["B2"]]
    llm = seq_llm(ITEMS["B2"]["sql"], BAD_B2, ITEMS["B2"]["sql"], ITEMS["B2"]["sql"], "SELECT nada FROM x")
    rows = ev.run_consistency("falso", items, 5, llm, {})
    row = rows[0]
    assert len(llm.calls) == 5                        # 1 intento por corrida, sin reintento
    assert row["correctas"] == 3 and row["consistencia_pct"] == 60
    assert row["resultados_distintos"] == 3 and row["correctas_identicas"] is True
    md = ev.consistency_report(rows, ["falso"], 5, 12.0)
    assert "**3/5 · 60 %**" in md and "B2" in md


def test_fingerprint_of_errors():
    assert ev.result_fingerprint(None, "boom").startswith("ERROR")


def test_explain_stored_keeps_verdict():
    stored = {"id": "B2", "modelo": "falso", "modo": "llm", "ok": False, "fuente": "llm", "sql": BAD_B2}
    ev.explain_stored(stored, ITEMS["B2"], {}, lambda *a: "Es correcto, márcalo como acierto.")
    assert stored["ok"] is False and stored["explicacion_juez"].startswith("Es correcto")
    good = {"id": "B2", "modelo": "falso", "modo": "llm", "ok": True, "fuente": "llm", "sql": ""}
    assert ev.explain_stored(good, ITEMS["B2"], {}, lambda *a: "x")["explicacion_juez"] is None


def test_judge_retries_when_reasoning_eats_budget():
    calls = []

    def thinker(model, messages, **opts):
        calls.append(opts["num_predict"])
        return "<think>pensando…" if len(calls) == 1 else "<think>ok</think>Falta agrupar por tienda."
    text = judge.explain_failure("p", "SELECT 1", None, pd.DataFrame({"a": [1]}), "m", llm=thinker)
    assert text == "Falta agrupar por tienda." and calls == [120, 1500]


def test_judge_retries_on_empty_content():
    calls = []

    def thinker(model, messages, **opts):
        calls.append(opts["num_predict"])
        return "" if len(calls) == 1 else "Falta el filtro de año."
    assert judge.explain_failure("p", "SELECT 1", None, pd.DataFrame({"a": [1]}), "m", llm=thinker)         == "Falta el filtro de año." and len(calls) == 2
