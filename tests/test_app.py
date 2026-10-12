"""Pruebas de la app con streamlit.testing.v1.AppTest (sin Ollama: backend y LLM falsos)."""

import pytest
from streamlit.testing.v1 import AppTest

import config

TIMEOUT = 90


class FakeBackend:
    """Imita la interfaz de ollama_manager."""

    def __init__(self, up=True, models=("qwen2.5:1.5b", "llama3.2:1b")):
        self.up = up
        self.models = list(models)
        self.unloaded, self.pulled = [], []

    def is_server_up(self):
        return self.up

    def try_start_server(self):
        self.up = True
        return True

    def list_local_models(self):
        return list(self.models)

    def unload_model(self, name):
        self.unloaded.append(name)

    def pull_model(self, name):
        self.pulled.append(name)
        for pct in (10.0, 60.0, 100.0):
            yield {"status": "descargando", "completed": pct, "total": 100, "percent": pct}
        self.models.append(name)

    def chat(self, *a, **k):
        raise AssertionError("las pruebas deben usar _llm_override")


class FakeLLM:
    def __init__(self, sql):
        self.sql = sql
        self.calls = 0

    def __call__(self, model, messages, **options):
        self.calls += 1
        if messages[0]["content"].startswith("Eres un analista"):
            return "Baldwin Bikes concentra la mayor parte de las órdenes."
        return f"```sql\n{self.sql}\n```"


def assistant(backend=None, llm=None) -> AppTest:
    at = AppTest.from_file(str(config.BASE_DIR / "app.py"), default_timeout=TIMEOUT)
    at.session_state["_ollama_backend"] = backend or FakeBackend()
    if llm is not None:
        at.session_state["_llm_override"] = llm
    at.run()
    at.switch_page("views/asistente.py").run()
    assert not at.exception, at.exception
    return at


def test_dashboard_loads():
    at = AppTest.from_file(str(config.BASE_DIR / "app.py"), default_timeout=TIMEOUT).run()
    assert not at.exception, at.exception
    assert [m.label for m in at.metric] == ["Ingreso neto", "Órdenes completadas", "Ticket promedio",
                                           "Descuento cedido", "Envíos tarde", "Perdido por rechazos"]
    assert at.metric[1].value == "1,445"
    assert len(at.get("plotly_chart")) == 11          # tendencia + 10 necesidades
    assert any("Valor de órdenes entregadas tarde" in m.value for m in at.markdown)


def test_dashboard_store_filter():
    at = AppTest.from_file(str(config.BASE_DIR / "app.py"), default_timeout=TIMEOUT).run()
    at.selectbox(key="dash_store").select("Rowlett Bikes").run()
    assert not at.exception, at.exception
    assert at.metric[1].value == "142"


def test_assistant_loads_with_suggestions():
    at = assistant()
    labels = [b.label for b in at.button]
    assert "+" in labels and len([b for b in at.button if b.key and b.key.startswith("sugg_")]) == 4
    assert any("● listo" in m.value for m in at.markdown)


def test_question_shows_answer_sql_and_table():
    llm = FakeLLM("SELECT store_name AS tienda, COUNT(*) AS ordenes FROM v_orders GROUP BY store_name")
    at = assistant(llm=llm)
    at.chat_input(key="chat_box").set_value("¿Cuántas órdenes tiene cada tienda?").run()
    assert not at.exception, at.exception
    assert any("Baldwin Bikes concentra" in m.value for m in at.markdown)
    assert any("Generada por IA" in m.value for m in at.markdown)
    assert at.code and "GROUP BY store_name" in at.code[0].value
    assert len(at.dataframe) == 1 and len(at.dataframe[0].value) == 3
    assert len(at.session_state["history"]) == 1


def test_verified_question_works_with_ollama_off():
    at = assistant(backend=FakeBackend(up=False))
    assert any("Ollama está apagado" in m.value for m in at.markdown)
    at.chat_input(key="chat_box").set_value("Pedidos entregados tarde por sucursal").run()
    assert not at.exception, at.exception
    assert any("Verificada" in m.value for m in at.markdown)
    assert any("458 órdenes" in m.value for m in at.markdown)   # respuesta de plantilla, sin LLM
    # Los montos se escapan: "$2,042,907.07 ... $..." no debe renderizarse como fórmula LaTeX
    answer = next(m.value for m in at.markdown if "458 órdenes" in m.value)
    assert r"\$2,042,907.07" in answer and "$" not in answer.replace(r"\$", "")


def test_model_change_resets_conversation():
    backend = FakeBackend()
    llm = FakeLLM("SELECT COUNT(*) AS n FROM orders")
    at = assistant(backend=backend, llm=llm)
    at.chat_input(key="chat_box").set_value("¿Cuántas órdenes hay?").run()
    assert len(at.session_state["messages"]) == 2
    at.selectbox(key="model_select").select("deepseek-r1:1.5b").run()
    assert not at.exception, at.exception
    assert at.session_state["messages"] == [] and at.session_state["history"] == []
    assert backend.unloaded == ["qwen2.5:1.5b"] and backend.pulled == ["deepseek-r1:1.5b"]
    assert any("deepseek-r1:1.5b activo; conversación reiniciada" in t.value for t in at.toast)


def test_plus_button_shows_toast():
    at = assistant()
    at.button(key="plus_btn").click().run()
    assert not at.exception, at.exception
    assert [t.value for t in at.toast] == ["Próximamente"]
    assert at.session_state["messages"] == []


def test_ai_writing_toggle_controls_verified_synthesis():
    llm = FakeLLM("SELECT 1")
    at = assistant(llm=llm)
    at.chat_input(key="chat_box").set_value("Pedidos entregados tarde por sucursal").run()
    assert llm.calls == 0                                       # por defecto: plantilla, sin LLM
    assert any("458 órdenes" in m.value for m in at.markdown)
    at.toggle(key="ai_writing").set_value(True).run()
    at.chat_input(key="chat_box").set_value("Pedidos entregados tarde por sucursal").run()
    assert not at.exception, at.exception
    assert llm.calls == 1                                       # con el toggle: síntesis con LLM
    assert any("Baldwin Bikes concentra" in m.value for m in at.markdown)


def test_sin_ia_mode_banner(monkeypatch):
    monkeypatch.setattr(config, "AI_DISABLED", True)
    at = AppTest.from_file(str(config.BASE_DIR / "app.py"), default_timeout=TIMEOUT).run()
    at.switch_page("views/asistente.py").run()
    assert not at.exception, at.exception
    assert any("Modo sin IA" in m.value for m in at.markdown)
    assert any("○ modo sin IA" in m.value for m in at.markdown)
    at.chat_input(key="chat_box").set_value("Pedidos entregados tarde por sucursal").run()
    assert any("Verificada" in m.value for m in at.markdown)


def test_background_pull_indicator(monkeypatch, tmp_path):
    import pull_log
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path)
    log, lock = pull_log.paths("qwen2.5:1.5b", tmp_path)
    lock.write_text("1", encoding="utf-8")
    log.write_text("pulling abc\t37.0\n", encoding="utf-8")
    at = assistant()
    assert any("↓ descargando… 37 %" in m.value for m in at.markdown)


def test_model_downloaded_but_not_loaded_shows_loading_and_warms_up():
    class ColdBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.warmed = []

        def is_model_loaded(self, name):
            return False

        def start_warm_up(self, name):
            self.warmed.append(name)

    backend = ColdBackend()
    at = assistant(backend=backend)
    assert any("◐ cargando…" in m.value for m in at.markdown)
    assert backend.warmed and backend.warmed[0] == "qwen2.5:1.5b"


def test_loaded_model_shows_ready():
    class WarmBackend(FakeBackend):
        def is_model_loaded(self, name):
            return True
    at = assistant(backend=WarmBackend())
    assert any("● listo" in m.value for m in at.markdown)


def test_missing_database_shows_clear_error(monkeypatch, tmp_path):
    at = AppTest.from_file(str(config.BASE_DIR / "app.py"), default_timeout=TIMEOUT)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "no_existe.db")
    at.run()
    assert at.error and "python database_builder.py" in at.code[0].value


# --- Fase 9: intentos visibles, modo juez y accesos directos -----------------------------

import yaml  # noqa: E402

from business_queries import BY_ID, render_sql  # noqa: E402

CANONICAL = {k: v["pregunta"] for k, v in yaml.safe_load(
    (config.BASE_DIR / "reference_answers.yaml").read_text(encoding="utf-8")).items()}
N8_BAD = "SELECT ROUND(AVG(net_amount), 2) AS ticket FROM v_order_lines WHERE order_status = 4"


class JudgeLLM:
    """SQL en orden para el modelo que contesta, crítica fija para el juez y frase para la síntesis."""

    def __init__(self, *sqls):
        self.sqls, self.calls = list(sqls), []

    def __call__(self, model, messages, **options):
        system = messages[0]["content"]
        role = "juez" if system.startswith("Eres un revisor") else (
            "sintesis" if system.startswith("Eres un analista") else "sql")
        self.calls.append((role, model))
        if role == "juez":
            return "Calcula el promedio por orden y agrupa por tienda."
        if role == "sintesis":
            return "Resumen de prueba."
        return f"```sql\n{self.sqls.pop(0) if len(self.sqls) > 1 else self.sqls[0]}\n```"


def expanders(at):
    return [e.label for e in at.expander]


def test_toggle_off_verified_route_is_instant_single_attempt():
    llm = JudgeLLM("SELECT 1")
    at = assistant(llm=llm)
    assert at.toggle(key="judge_mode").value is False
    at.chat_input(key="chat_box").set_value(CANONICAL["N8"]).run()
    assert not at.exception, at.exception
    r = at.session_state["messages"][-1]["result"]
    assert r.source == "verificada" and sum(r.timings.values()) < 0.1 and len(r.intentos) == 1
    assert any("Intentos (1) — acertó a la primera" in m.value for m in at.markdown)
    assert any("Intento 1** — ✓ acertó" in m.value for m in at.markdown)
    assert not any(label.startswith("Intentos") for label in expanders(at))   # sin colapsar
    assert llm.calls == []                                      # sin LLM, como siempre
    assert any("<0.1 s · sin LLM · 1 intento" in c.value for c in at.caption)


def test_toggle_on_need_uses_judge_and_shows_attempts():
    llm = JudgeLLM(N8_BAD, render_sql(BY_ID["N8"]))
    at = assistant(llm=llm)
    at.toggle(key="judge_mode").set_value(True).run()
    assert at.selectbox(key="judge_model").value == "Mismo modelo"
    at.chat_input(key="chat_box").set_value(CANONICAL["N8"]).run()
    assert not at.exception, at.exception
    r = at.session_state["messages"][-1]["result"]
    assert r.source == "llm" and r.reference_id == "N8" and r.reference_match is True
    assert [i["exito"] for i in r.intentos] == [False, True]
    assert "Intentos (2)" in expanders(at)
    assert any("Intento 1** — ✗ falló" in m.value for m in at.markdown)
    assert any("Intento 2** — ✓ acertó" in m.value for m in at.markdown)
    assert any("Generada por IA" in m.value for m in at.markdown)
    assert not any("badge-verificada" in m.value for m in at.markdown)
    assert any("consulta verificada N8: coincide" in m.value for m in at.markdown)
    assert {model for _, model in llm.calls} == {"qwen2.5:1.5b"}  # un solo modelo, dos roles
    assert ("juez", "qwen2.5:1.5b") in llm.calls


def test_toggle_on_free_question_has_no_reference():
    llm = JudgeLLM("SELECT COUNT(*) AS n FROM customers")
    at = assistant(llm=llm)
    at.toggle(key="judge_mode").set_value(True).run()
    at.chat_input(key="chat_box").set_value("¿Cuántos clientes hay?").run()
    assert not at.exception, at.exception
    r = at.session_state["messages"][-1]["result"]
    assert r.reference_id is None and r.reference_match is None and len(r.intentos) == 3
    assert all(i["exito"] is None for i in r.intentos)
    assert any("sin referencia para comprobarlo" in m.value for m in at.markdown)
    assert any("Generada por IA" in m.value for m in at.markdown)


@pytest.mark.parametrize("need", [f"N{i}" for i in range(1, 11)])
def test_need_shortcut_sends_canonical_question(need):
    at = assistant(llm=JudgeLLM("SELECT 1"))
    at.button(key=f"need_{need}").click().run()
    assert not at.exception, at.exception
    msgs = at.session_state["messages"]
    assert msgs[0]["content"] == CANONICAL[need]
    assert msgs[1]["result"].source == "verificada" and msgs[1]["result"].business_query_id == need
