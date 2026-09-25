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
