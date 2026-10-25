"""Fase 11, módulo D/F: modos de contexto en el motor y pipeline del harness (LLM falso)."""

import pytest

import bridge
import config
import database_builder
import eval_text2sql as ev
import fewshot
import harness
import netmode
import sql_engine as se
from necesidades_negativas import catalogo

ITEMS = {it["id"]: it for it in ev.load_golden()}


@pytest.fixture(scope="module", autouse=True)
def database():
    database_builder.build_database()


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / ".cache")
    monkeypatch.setattr(config, "MODO_RED", "offline")
    fewshot.reset_cache()
    yield
    fewshot.reset_cache()


class Script:
    """LLM falso: devuelve las respuestas en orden (la última se repite) y registra cada llamada."""

    def __init__(self, *sqls):
        self.sqls = list(sqls)
        self.calls = []

    def __call__(self, model, messages, **opts):
        self.calls.append({"messages": messages, "opts": opts})
        sql = self.sqls.pop(0) if len(self.sqls) > 1 else self.sqls[0]
        return f"```sql\n{sql}\n```"


GOOD = "SELECT COUNT(*) AS n FROM customers"
BAD_COLUMN = "SELECT customer_name FROM customers"
Q = "¿Cuántos clientes hay?"


class FakeBridge:
    name, model, reason = "fake", "m-grande", ""

    def __init__(self, sql):
        self.sql, self.calls = sql, 0

    def available(self):
        return True

    def chat(self, messages):
        self.calls += 1
        return bridge.BridgeResult(f"```sql\n{self.sql}\n```", self.name, self.model)


# --- modo base: nada cambia ----------------------------------------------------------------------

def test_base_prompt_is_exactly_the_old_one():
    schema, ref_date, _ = se._schema_context_cached(str(config.DB_PATH.resolve()))
    examples = "\n\n".join(f"Pregunta: {q}\n```sql\n{sql}\n```" for q, sql in se.FEW_SHOTS)
    old = se.SYSTEM_PROMPT_TEMPLATE.format(schema=schema, reference_date=ref_date, examples=examples)
    assert se.build_system_prompt() == old
    assert se.build_system_prompt(prompt_extra={}) == old
    assert se.build_sql_messages(Q)[0]["content"] == old


def test_base_mode_sends_the_same_messages_as_before():
    a, b = Script(GOOD), Script(GOOD)
    ra = se.answer_question(Q, "m", llm=a, use_router=False, synthesize_answer=False)
    rb = se.answer_question(Q, "m", llm=b, use_router=False, synthesize_answer=False, modo_contexto="base")
    assert a.calls == b.calls and ra.source == rb.source == "llm" and rb.ejemplos == [] and rb.modo_contexto == "base"


def test_unknown_context_mode_is_reported_not_raised():
    res = se.answer_question(Q, "m", llm=Script(GOOD), use_router=False, modo_contexto="inventado")
    assert res.error and "modo_contexto" in res.error


# --- fewshot / rag ---------------------------------------------------------------------------------

@pytest.mark.parametrize("modo", ["fewshot", "rag"])
def test_examples_are_appended_after_the_production_examples(modo):
    llm = Script(GOOD)
    res = se.answer_question("¿Cuánto cuestan los envíos tardíos por tienda?", "m", llm=llm,
                             use_router=False, synthesize_answer=False, modo_contexto=modo)
    prompt = llm.calls[0]["messages"][0]["content"]
    assert se.FEW_SHOTS[-1][0] in prompt and fewshot.HEADER in prompt
    assert prompt.index(se.FEW_SHOTS[-1][0]) < prompt.index(fewshot.HEADER)
    assert res.source == "llm_ejemplos" and res.modo_contexto == modo
    assert res.ejemplos and {"id", "pregunta", "score", "origen"} <= set(res.ejemplos[0])
    assert res.traza[0]["etapa"] == "recuperacion"
    assert all("sql" not in e for e in res.ejemplos)           # el rastro visible no lleva SQL


def test_rag_without_hits_above_threshold_leaves_the_prompt_untouched():
    llm = Script(GOOD)
    res = se.answer_question("receta de paella valenciana", "m", llm=llm, use_router=False,
                             synthesize_answer=False, modo_contexto="rag")
    assert llm.calls[0]["messages"][0]["content"] == se.build_system_prompt()
    assert res.source == "llm" and res.ejemplos == [] and "ningún ejemplo superó el umbral" in res.traza[0]["nota"]


def test_rag_trims_the_schema_and_reports_it():
    llm = Script(GOOD)
    res = se.answer_question("ticket promedio por tienda", "m", llm=llm, use_router=False,
                             synthesize_answer=False, modo_contexto="rag")
    prompt = llm.calls[0]["messages"][0]["content"]
    assert res.traza[0]["esquema_recortado"] and "customers(" not in prompt
    assert len(prompt) < len(se.build_system_prompt()) + config.FEWSHOT_MAX_CHARS + 200


def test_verified_route_never_calls_the_llm_in_any_mode():
    for modo in ("base", "fewshot", "rag", "harness"):
        llm = Script(GOOD)
        res = se.answer_question("¿Cuánto dinero perdimos por pedidos rechazados?", "m", llm=llm,
                                 synthesize_answer=False, modo_contexto=modo)
        assert res.source == "verificada" and llm.calls == [], modo


# --- harness ---------------------------------------------------------------------------------------

def stages(res):
    return [t["etapa"] for t in res.traza]


def test_harness_stage_order_and_labels():
    llm = Script(GOOD)
    res = harness.run("¿Cuánto cuestan los envíos tardíos por tienda?", "m", llm=llm)
    assert stages(res) == ["ruteo", "recuperacion", "generacion"]
    assert res.modo_contexto == "harness" and res.source == "llm_ejemplos" and res.modo_red == "offline"
    assert res.traza[0] == {"etapa": "ruteo", "resultado": "llm", "usa_llm": True}
    assert res.traza[2]["validacion_estatica"] == "columnas" and res.traza[2]["ok"]


def test_harness_repairs_hallucinated_column_without_touching_the_db():
    llm = Script(BAD_COLUMN, GOOD)
    res = harness.run(Q, "m", llm=llm, max_attempts=2)
    assert res.error is None and len(llm.calls) == 2 and res.df.iat[0, 0] > 0
    feedback = llm.calls[1]["messages"][-1]["content"]
    assert "customer_name" in feedback and "no existe" in feedback and "first_name" in feedback
    assert res.intentos[0]["exito"] is False and res.intentos[1]["exito"] is True


def test_harness_repair_feedback_never_carries_the_reference():
    item = ITEMS["B2"]
    ref = se.execute_sql(se.validate_sql(item["sql"]))
    llm = Script("SELECT ROUND(SUM(net_total), 2) AS x FROM v_orders WHERE order_status = 3", item["sql"])
    check = ev.make_attempt_check(item, ref)
    res = harness.run(item["pregunta"], "m", llm=llm, max_attempts=2, attempt_check=check,
                      contexto_opts={"exclude_sql": [item["sql"]], "exclude_questions": [item["pregunta"]]})
    feedback = llm.calls[1]["messages"][-1]["content"]
    ref_value = str(ref.iat[0, 0])
    assert ref_value not in feedback and item["sql"] not in feedback
    assert res.hit_attempt == 2


def test_harness_respects_max_attempts():
    for n in (1, 2, 3):
        llm = Script(BAD_COLUMN)
        res = harness.run(Q, "m", llm=llm, max_attempts=n)
        assert len(llm.calls) == n and res.error and res.df is None


def test_harness_verified_route_skips_retrieval_and_llm():
    llm = Script(GOOD)
    res = harness.run("¿Cuánto dinero perdimos por pedidos rechazados?", "m", llm=llm, use_router=True)
    assert res.source == "verificada" and llm.calls == []
    assert stages(res)[0] == "ruteo" and res.traza[0]["usa_llm"] is False
    assert "recuperacion" not in stages(res)


def test_harness_consistency_votes_for_the_most_frequent_result():
    other = "SELECT COUNT(*) AS n FROM stores"
    llm = Script(other, GOOD, GOOD)                 # 1.ª muestra distinta, las otras dos coinciden
    res = harness.run(Q, "m", llm=llm, consistencia=3)
    assert res.sql.endswith("customers") or "customers" in res.sql
    vote = next(t for t in res.traza if t["etapa"] == "consistencia")
    assert vote["muestras"] == 3 and vote["votos_ganador"] == 2
    assert llm.calls[1]["opts"]["temperature"] > 0 and llm.calls[0]["opts"]["temperature"] == 0


def test_static_check_has_no_false_positives_on_known_good_sql():
    for it in ITEMS.values():
        assert harness.check_columns(it["sql"]) is None, it["id"]
    for r in catalogo.load_catalog():
        assert harness.check_columns(r["sql"]) is None, r["id"]
    assert harness.check_columns("SELECT category_name FROM v_orders")
    assert harness.check_columns("SELEC mal") is None            # de eso se encarga validate_sql


# --- escalamiento ----------------------------------------------------------------------------------

def test_escalation_is_skipped_offline_and_reports_why():
    llm = Script(BAD_COLUMN)
    fake = FakeBridge(GOOD)
    res = harness.run(Q, "m", llm=llm, max_attempts=1, escalar=True, bridge=bridge.NullBridge("modo de red offline"))
    esc = next(t for t in res.traza if t["etapa"] == "escalamiento")
    assert esc["estado"] == "omitido" and "offline" in esc["motivo"]
    assert res.error and res.source != "llm_grande" and fake.calls == 0


def test_escalation_online_resolves_and_validates_the_big_model_sql(monkeypatch):
    monkeypatch.setattr(config, "MODO_RED", "online")
    fake = FakeBridge(GOOD)
    res = harness.run(Q, "m", llm=Script(BAD_COLUMN), max_attempts=1, escalar=True, bridge=fake)
    assert res.error is None and res.source == "llm_grande" and res.df.iat[0, 0] > 0
    assert fake.calls == 1 and res.modo_red == "online"
    assert next(t for t in res.traza if t["etapa"] == "escalamiento")["estado"] == "resuelto"


@pytest.mark.parametrize("dangerous", ["DROP TABLE customers", "DELETE FROM customers",
                                       "SELECT 1; DROP TABLE customers", "SELECT * FROM tabla_falsa"])
def test_escalation_rejects_unsafe_sql_from_the_big_model(monkeypatch, dangerous):
    monkeypatch.setattr(config, "MODO_RED", "online")
    res = harness.run(Q, "m", llm=Script(BAD_COLUMN), max_attempts=1, escalar=True, bridge=FakeBridge(dangerous))
    esc = next(t for t in res.traza if t["etapa"] == "escalamiento")
    assert esc["estado"] in ("sql_rechazada", "sin_sql") and res.source != "llm_grande" and res.error
    assert se.execute_sql("SELECT COUNT(*) FROM customers").iat[0, 0] > 0      # la tabla sigue ahí


def test_escalation_does_not_trigger_when_the_local_model_succeeded():
    fake = FakeBridge("SELECT 99")
    res = harness.run(Q, "m", llm=Script(GOOD), escalar=True, bridge=fake)
    assert fake.calls == 0 and not any(t["etapa"] == "escalamiento" for t in res.traza)

