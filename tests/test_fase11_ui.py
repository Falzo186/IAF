"""Fase 11: selector de contexto y modo de red en el Asistente, y la página de comparativa.

Se prueba la página directamente (AppTest.from_file sobre views/...), sin pasar por el dashboard.
"""

import json

import pytest
from streamlit.testing.v1 import AppTest

import config
import database_builder
import fewshot
from tests.test_app import FakeBackend, FakeLLM

TIMEOUT = 90
PAGE = str(config.BASE_DIR / "views" / "asistente.py")


@pytest.fixture(scope="module", autouse=True)
def database():
    database_builder.build_database()


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    # La página escribe config.MODO_RED y config.BRIDGE_ENABLED: monkeypatch los restaura al terminar.
    monkeypatch.setattr(config, "MODO_RED", "offline")
    monkeypatch.setattr(config, "BRIDGE_ENABLED", False)
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / ".cache")
    fewshot.reset_cache()


def page(llm=None) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=TIMEOUT)
    at.session_state["_ollama_backend"] = FakeBackend()
    at.session_state["_llm_override"] = llm or FakeLLM("SELECT COUNT(*) AS n FROM customers")
    at.run()
    assert not at.exception, at.exception
    return at


def badges(at):
    return " ".join(m.value for m in at.markdown if "badge" in m.value)


def ask(at, question):
    at.chat_input[0].set_value(question).run()
    assert not at.exception, at.exception
    return at


def test_default_is_base_context_offline_with_visible_indicator():
    at = page()
    assert at.selectbox(key="context_mode").value == "Base"
    assert at.radio(key="net_mode").value == "Local offline"
    assert "OFFLINE" in badges(at) and "ONLINE" not in badges(at)
    assert config.MODO_RED == "offline"
    assert at.selectbox(key="context_mode").options == ["Base", "Few shot", "RAG", "Harness"]
    assert set(at.selectbox(key="model_select").options) == set(config.SUPPORTED_MODELS)


def test_base_answer_looks_like_before():
    at = ask(page(), "¿Cuántos clientes hay?")
    text = badges(at)
    assert "Generada por IA" in text and "IA + ejemplos" not in text and "Contexto:" not in text
    assert not any(e.label.startswith(("Ejemplos recuperados", "Traza")) for e in at.expander)


def test_rag_shows_retrieved_examples_without_their_sql():
    at = page()
    at.selectbox(key="context_mode").select("RAG").run()
    ask(at, "¿Cuánto cuestan los envíos tardíos por tienda?")
    assert "IA + ejemplos" in badges(at) and "Contexto: rag" in badges(at)
    exp = next(e for e in at.expander if e.label.startswith("Ejemplos recuperados"))
    body = " ".join(m.value for m in exp.markdown)
    assert "puntaje" in body and "SELECT" not in body.upper()


def test_harness_shows_its_trace():
    at = page()
    at.selectbox(key="context_mode").select("Harness").run()
    ask(at, "¿Cuántos clientes hay en cada ciudad de Texas?")
    exp = next(e for e in at.expander if e.label == "Traza del harness")
    body = " ".join(m.value for m in exp.markdown)
    assert "Ruteo" in body and "Recuperación" in body and "Generación" in body


def test_online_without_a_key_keeps_working_locally_and_says_why(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    at = page()
    at.radio(key="net_mode").set_value("Online gratis").run()
    assert not at.exception
    assert "ONLINE" in badges(at)
    assert any("Puente online no disponible" in c.value for c in at.caption)
    ask(at, "¿Cuántos clientes hay?")
    assert at.session_state["messages"][-1]["result"].source == "llm"      # sigue en local, sin error
    assert at.session_state["messages"][-1]["result"].error is None


class CapturingLLM(FakeLLM):
    def __init__(self, sql):
        super().__init__(sql)
        self.prompts = []

    def __call__(self, model, messages, **options):
        self.prompts.append(messages[0]["content"])
        return super().__call__(model, messages, **options)


def test_judge_mode_with_rag_hides_the_reference_sql_from_the_model():
    from business_queries import BY_ID, render_sql
    llm = CapturingLLM("SELECT 1 AS x")
    at = page(llm)
    at.selectbox(key="context_mode").select("RAG").run()
    at.toggle(key="judge_mode").set_value(True).run()
    ask(at, "¿Cuánto dinero perdimos por pedidos rechazados?")
    ref_sql = " ".join(render_sql(BY_ID["N10"]).lower().split())
    generation_prompts = [p for p in llm.prompts if p.startswith("Eres un experto en SQL")]
    assert generation_prompts and all(ref_sql not in " ".join(p.lower().split()) for p in generation_prompts)


# --- página de comparativa --------------------------------------------------------------------

COMPARATIVA = str(config.BASE_DIR / "views" / "comparativa_fase11.py")


def test_comparativa_without_results_explains_how_to_generate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    at = AppTest.from_file(COMPARATIVA, default_timeout=TIMEOUT).run()
    assert not at.exception and any("eval_fase11.py" in i.value for i in at.info)


def test_comparativa_reads_results_and_flags_simulated_runs(tmp_path, monkeypatch):
    out = tmp_path / "eval" / "fase11"
    out.mkdir(parents=True)
    rows = [{"modelo": "m", "modo": modo, "politica": "n/a" if modo == "base" else "sin_gemelas",
             "conjunto": conj, "ok": ok, "ejecutable": True, "alucina_columnas": False, "intentos": 1,
             "latencia_s": 1.0}
            for modo in ("base", "fewshot", "rag", "harness") for conj in ("golden", "negativas_heldout")
            for ok in (True, False)]
    (out / "resultados.json").write_text(json.dumps({"meta": {"simulado": True, "red": "offline",
                                                              "conexiones_externas": 0}, "resultados": rows}),
                                         encoding="utf-8")
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    at = AppTest.from_file(COMPARATIVA, default_timeout=TIMEOUT).run()
    assert not at.exception and any("SIMULADOS" in w.value for w in at.warning)
    table = at.dataframe[0].value
    assert list(table.columns) == ["Modelo", "Conjunto", "Base", "Few shot", "RAG", "Harness"]
    assert table.iloc[0]["Base"] == "1/2 (50 %)"
