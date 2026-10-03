"""Fase 7: niveles de contexto, experimento de contexto, bitácora de patrones y su revisión manual."""

import json

import pandas as pd
import pytest

import config
import context_experiment as cx
import database_builder
import eval_text2sql as ev
import learned_patterns as lp
import review_patterns as rp
import sql_engine as se


@pytest.fixture(scope="module", autouse=True)
def database():
    database_builder.build_database()
    return config.DB_PATH


# --- Niveles de contexto ---------------------------------------------------------------

def test_default_prompt_is_unchanged_by_context_level_parameter():
    assert se.build_system_prompt() == se.build_system_prompt(context_level="actual")
    assert se.get_schema_context() in se.build_system_prompt()


def test_sin_contexto_has_only_table_names():
    schema = se.get_schema_context_level("sin_contexto")
    assert "v_order_lines" in schema and "customers" in schema
    assert "net_amount" not in schema and "Valores válidos" not in schema


def test_describe_completo_has_columns_types_and_foreign_keys():
    schema = se.get_schema_context_level("describe_completo")
    assert "TABLE orders" in schema and "VIEW v_orders" in schema
    assert "order_id INTEGER PRIMARY KEY" in schema
    assert "FOREIGN KEY (customer_id) REFERENCES customers(customer_id)" in schema
    assert "Valores válidos" not in schema  # es el resultado de PRAGMA, no el resumen manual


def test_sizes_grow_with_context_and_unknown_level_fails():
    sizes = cx.context_sizes()
    assert sizes["sin_contexto"]["esquema"] < sizes["actual"]["esquema"]
    with pytest.raises(ValueError):
        se.build_system_prompt(context_level="inventado")


# --- Experimento -----------------------------------------------------------------------

def test_experiment_runs_all_levels_and_restores_production_prompt():
    items = ev.load_golden()
    before = se.build_system_prompt
    results = cx.run_experiment("oraculo", ev.oracle_llm(items), items)
    assert se.build_system_prompt is before
    assert {r["contexto"] for r in results} == set(cx.LEVELS)
    assert len(results) == 3 * 20 and all(r["ok"] for r in results)
    report = cx.build_experiment_report(results, "oraculo", cx.context_sizes())
    assert "C · describe_completo" in report and "Distribución de categorías de falla" in report
    assert "NO mejora" in cx.verdict(results)  # empate: no se adopta


def test_experiment_sends_the_requested_context_to_the_llm():
    seen = {}

    def llm(model, messages, **_):
        seen.setdefault(len(seen), messages[0]["content"])
        return "```sql\nSELECT 1\n```"

    items = [it for it in ev.load_golden() if it["id"] == "B1"]
    cx.run_experiment("falso", llm, items, levels=["sin_contexto", "describe_completo"])
    assert "Tablas y vistas:" in seen[0] and "FOREIGN KEY" in seen[1]


# --- Bitácora --------------------------------------------------------------------------

def result(source="llm", sql="SELECT 1", error=None, df=True, question="¿Cuántos clientes hay?"):
    return se.QueryResult(question=question, model="qwen2.5:1.5b", sql=sql, source=source, error=error,
                          df=pd.DataFrame({"a": [1]}) if df else None)


def test_logs_llm_and_anchored_results_only():
    assert lp.log_pattern(result("llm")) and lp.log_pattern(result("llm_anclada"))
    assert not lp.log_pattern(result("verificada"))
    assert not lp.log_pattern(result("solo_lectura"))
    assert not lp.log_pattern(result(error="no such column"))
    assert not lp.log_pattern(result(sql=None))
    rows = lp.read_patterns()
    assert len(rows) == 2
    assert set(rows[0]) >= {"pregunta", "sql", "modelo", "timestamp", "db_hash"}
    assert rows[0]["db_hash"] == lp.db_hash() != "desconocido"


def test_log_is_append_only_and_never_raises(tmp_path):
    lp.log_pattern(result(question="uno"))
    lp.log_pattern(result(question="dos"))
    assert [r["pregunta"] for r in lp.read_patterns()] == ["uno", "dos"]
    assert lp.log_pattern(result(), path=tmp_path / "no" / "existe" / "x.jsonl") is False


def test_answer_question_does_not_log_by_itself():
    llm = lambda *a, **k: "```sql\nSELECT COUNT(*) AS n FROM customers\n```"  # noqa: E731
    se.answer_question("¿Cuántos clientes hay?", "m", llm=llm, synthesize_answer=False)
    assert lp.read_patterns() == []  # el registro lo hace la vista del chat, no el motor


# --- Revisión manual -------------------------------------------------------------------

def log_two_near_identical_and_one_different():
    sql = "SELECT COUNT(*) FROM customers"
    lp.log_pattern(result(sql=sql, question="¿Cuántos clientes hay en total?"))
    lp.log_pattern(result(sql=sql, question="Cuantos clientes hay en total"))
    lp.log_pattern(result(sql="SELECT AVG(list_price) FROM products",
                          question="Precio promedio de los productos"))


def test_near_identical_questions_share_a_group():
    log_two_near_identical_and_one_different()
    groups = rp.group_patterns(lp.read_patterns())
    assert sorted(len(g["items"]) for g in groups) == [1, 2]
    assert rp.similarity("¿Cuántos clientes hay?", "Cuantos clientes hay") > rp.SIMILARITY


def test_promote_adds_candidate_without_touching_production_prompt(tmp_path):
    log_two_near_identical_and_one_different()
    prompt_before, shots_before = se.build_system_prompt(), list(se.FEW_SHOTS)
    reviewed = tmp_path / "reviewed.json"
    group = next(g for g in rp.pending_groups(reviewed_path=reviewed) if len(g["items"]) == 2)

    rp.promote(group, reviewed_path=reviewed)

    assert ("¿Cuántos clientes hay en total?", "SELECT COUNT(*) FROM customers") in se.FEWSHOT_CANDIDATES
    assert se.load_fewshot_candidates() == [("¿Cuántos clientes hay en total?",
                                             "SELECT COUNT(*) FROM customers")]
    assert se.FEW_SHOTS == shots_before and se.build_system_prompt() == prompt_before
    assert "Cuántos clientes hay en total" not in se.build_system_prompt()
    assert len(rp.pending_groups(reviewed_path=reviewed)) == 1  # el promovido ya no está pendiente


def test_menu_promotes_discards_and_skips(tmp_path):
    log_two_near_identical_and_one_different()
    answers = iter(["p", "d"])
    out = []
    stats = rp.run_menu(reviewed_path=tmp_path / "r.json", input_fn=lambda _: next(answers), out=out.append)
    assert stats == {"promovidos": 1, "descartados": 1, "saltados": 0}
    assert rp.pending_groups(reviewed_path=tmp_path / "r.json") == []
    assert len(json.loads(config.FEWSHOT_CANDIDATES_PATH.read_text(encoding="utf-8"))) == 1
    assert any("NO activa nada solo" in line for line in out)


def test_menu_quit_leaves_groups_pending(tmp_path):
    log_two_near_identical_and_one_different()
    stats = rp.run_menu(reviewed_path=tmp_path / "r.json", input_fn=lambda _: "q", out=lambda _: None)
    assert stats["saltados"] == 2 and len(rp.pending_groups(reviewed_path=tmp_path / "r.json")) == 2
