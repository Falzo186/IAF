"""Fase 10: solo 3 modelos en los selectores, el juez no entrega SQL resuelta y la síntesis usa
el total real calculado en Python. Sin Ollama."""

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import config
import feedback as fb
import sql_engine as se
from business_queries import BY_ID, render_sql, run_business_query
from tests.test_app import FakeBackend, TIMEOUT

# --- 1. selectores de modelo ----------------------------------------------------------

LOCAL = ("qwen2.5:1.5b", "llama3.2:1b", "qwen3:4b", "qwen2.5:7b", "mistral:latest")


def test_model_selectors_only_offer_supported_models():
    at = AppTest.from_file(str(config.BASE_DIR / "app.py"), default_timeout=TIMEOUT)
    at.session_state["_ollama_backend"] = FakeBackend(models=LOCAL)
    at.run()
    at.switch_page("views/asistente.py").run()
    assert not at.exception, at.exception
    assert list(at.selectbox(key="model_select").options) == config.SUPPORTED_MODELS
    at.toggle(key="judge_mode").set_value(True).run()
    assert list(at.selectbox(key="judge_model").options) == ["Mismo modelo"] + config.SUPPORTED_MODELS
    # deepseek no está descargado: se ofrece igual (con "↓ no descargado"), pero nada de 4b ni 7b
    at.selectbox(key="model_select").select("deepseek-r1:1.5b")
    assert all("7b" not in o and "4b" not in o for o in at.selectbox(key="model_select").options)


def test_unsupported_active_model_falls_back_to_default():
    at = AppTest.from_file(str(config.BASE_DIR / "app.py"), default_timeout=TIMEOUT)
    at.session_state["_ollama_backend"] = FakeBackend(models=LOCAL)
    at.session_state["active_model"] = "qwen3:4b"
    at.run()
    at.switch_page("views/asistente.py").run()
    assert not at.exception, at.exception
    assert at.selectbox(key="model_select").value == config.DEFAULT_MODEL


# --- 2. el juez no entrega SQL resuelta --------------------------------------------------

SQL_CRITIQUE = (
    "La consulta no agrupa por tienda. Usa esta:\n```sql\nSELECT store_name, AVG(net_total)\n"
    "FROM v_orders\nGROUP BY store_name\n```\nTambién podrías escribir `SELECT 1` o\n"
    "SELECT store_name FROM v_orders GROUP BY store_name;\nRevisa el nivel de agregación."
)


def test_strip_sql_keeps_only_prose():
    out = fb.strip_sql(SQL_CRITIQUE)
    assert "SELECT" not in out.upper() and "```" not in out and "`" not in out
    assert "no agrupa por tienda" in out and "nivel de agregación" in out
    assert "SELECT" not in fb.sanitize(SQL_CRITIQUE, None).upper()


def test_judge_prompt_forbids_sql():
    import judge
    assert "NUNCA escribas un bloque de código ni una consulta SQL" in judge.CRITIC_SYSTEM


class CodeJudgeLLM:
    def __init__(self, sql):
        self.sql, self.calls = sql, []

    def __call__(self, model, messages, **options):
        role = "juez" if messages[0]["content"].startswith("Eres un revisor") else "sql"
        self.calls.append((role, messages))
        return SQL_CRITIQUE if role == "juez" else f"```sql\n{self.sql}\n```"


@pytest.mark.parametrize("with_reference", [True, False])
def test_judge_sql_never_reaches_next_attempt(with_reference):
    bad = "SELECT ROUND(AVG(net_amount), 2) AS ticket FROM v_order_lines WHERE order_status = 4"
    llm = CodeJudgeLLM(bad)
    ref = se.reference_for(BY_ID["N8"]) if with_reference else None
    r = se.answer_with_judge("¿Cuánto gasta en promedio un cliente por pedido en cada tienda?",
                             "falso", referencia=ref, max_intentos=3, llm=llm)
    retries = [m[-1]["content"] for role, m in llm.calls if role == "sql" and len(m) > 2]
    assert len(retries) == 2
    for msg in retries:
        critique = msg.split("\n")[0]                  # la línea con el feedback (sin la instrucción)
        assert "SELECT" not in critique.upper() and "```" not in critique
        assert "no agrupa por tienda" in critique
    for i in r.intentos[:-1]:
        assert "SELECT" not in (i["diagnostico"] or "").upper()


# --- 3. la síntesis usa el total real ------------------------------------------------------

DF8 = pd.DataFrame({"producto": [f"P{i}" for i in range(1, 9)],
                    "unidades": [10, 20, 30, 40, 50, 60, 70, 80],
                    "precio_lista": [100.0] * 8,
                    "valor": [1000.5, 2000.25, 3000.0, 4000.0, 5000.0, 6000.0, 7000.0, 8000.0]})
TOTAL = 36000.75       # suma de las 8 filas
PARTIAL = 6000.75      # lo que "suma" un LLM que solo mira las 3 primeras


class BadAdderLLM:
    """LLM de síntesis que suma mal: da un total parcial."""

    def __init__(self, text=f"El total es ${PARTIAL:,.2f} en valor inmovilizado y suman 60 unidades."):
        self.text, self.messages = text, None

    def __call__(self, model, messages, **options):
        self.messages = messages
        return self.text


def test_totals_computed_on_full_dataframe():
    totals = se.compute_totals("¿Cuánto capital tenemos parado en total?", DF8)
    assert totals == {"unidades": 360.0, "valor": TOTAL}      # precio_lista no se suma


def test_synthesis_uses_total_real_not_partial_sum():
    llm = BadAdderLLM()
    text, called = se.synthesize("¿Cuánto capital tenemos parado en total?", "SELECT …", DF8, "m", llm)
    assert called
    prompt = llm.messages[1]["content"]
    assert "total_real" in prompt and "no lo recalcules" in prompt and "$36,000.75" in prompt
    assert "$36,000.75" in text and "$6,000.75" not in text
    assert "360" in text and "60 unidades" not in text.replace("360 unidades", "")


def test_synthesis_appends_total_when_llm_omits_it():
    text, _ = se.synthesize("¿Cuánto dinero suman?", "SELECT …", DF8, "m",
                            BadAdderLLM("El producto P8 es el de mayor valor."))
    assert text.endswith("El total real es $36,000.75.")


def test_no_total_for_averages_or_rankings():
    assert not se.wants_total("¿Cuánto gasta en promedio un cliente por pedido en cada tienda?")
    assert not se.wants_total("¿Cuáles son los 5 productos con más unidades vendidas?")
    llm = BadAdderLLM("Rowlett Bikes tiene el ticket más alto.")
    text, _ = se.synthesize("¿Cuál es el ticket promedio por tienda?", "SELECT …", DF8, "m", llm)
    assert text == "Rowlett Bikes tiene el ticket más alto." and "total_real" not in llm.messages[1]["content"]


def test_existing_total_row_is_used_instead_of_summing():
    n10 = run_business_query(BY_ID["N10"])
    totals = se.compute_totals("¿Cuánto dinero perdimos por pedidos que no se concretaron?", n10)
    assert totals["monto_neto_perdido"] == pytest.approx(208579.45)   # fila "Total", no la suma


def test_all_routes_use_total_real():
    q = "¿Qué mercancía lleva meses en bodega sin moverse y cuánto capital tenemos ahí parado?"
    n6 = run_business_query(BY_ID["N6"])
    real = f"${n6['valor_inmovilizado'].sum():,.2f}"
    partial = f"${n6['valor_inmovilizado'].head(15).sum():,.2f}"
    wrong = BadAdderLLM(f"En total hay {partial} inmovilizados.")
    # verificada con "Redacción con IA"
    llm = _Seq(wrong)
    r = se.answer_question(q, "falso", llm=llm, verified_synthesis=True)
    assert r.source == "verificada" and real in r.answer and partial not in r.answer
    # LLM libre (sin enrutador)
    llm = _Seq(f"```sql\n{render_sql(BY_ID['N6'])}\n```", wrong)
    r = se.answer_question(q, "falso", llm=llm, use_router=False)
    assert r.source == "llm" and real in r.answer and partial not in r.answer


class _Seq:
    def __init__(self, *responses):
        self.responses = list(responses)

    def __call__(self, model, messages, **options):
        item = self.responses.pop(0)
        return item(model, messages, **options) if callable(item) else item
