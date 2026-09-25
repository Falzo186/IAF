"""Página Asistente: chat Text-to-SQL con modelos locales de Ollama.

Para las pruebas se pueden inyectar en st.session_state:
    _llm_override     callable(model, messages, **options) -> str
    _ollama_backend   objeto con la interfaz de ollama_manager
"""

import time

import pandas as pd
import streamlit as st

import config
import ollama_manager
import pull_log
import warmup
import sql_engine as se
from ui import charts

ss = st.session_state
ss.setdefault("messages", [])        # [{"role": "user", "content": str} | {"role": "assistant", "result": QueryResult}]
ss.setdefault("history", [])         # [{"question", "sql"}] para preguntas de seguimiento
ss.setdefault("active_model", config.DEFAULT_MODEL)
ss.setdefault("ai_writing", config.VERIFIED_SYNTHESIS)

SOURCE_BADGES = {
    "verificada": ("Verificada", "badge-verificada"),
    "llm_anclada": ("IA anclada", "badge-anclada"),
    "llm": ("Generada por IA", "badge-llm"),
    "solo_lectura": ("Solo lectura", "badge-anclada"),
}
SUGGESTIONS = [
    "¿Qué productos se venden mucho pero están a punto de agotarse?",
    "¿Cuánto dinero perdimos por pedidos rechazados?",
    "Ticket promedio por tienda en 2017",
    "¿Cuáles son las 5 marcas con más unidades vendidas?",
]
STATUS_TTL_S = 10


def backend():
    return ss.get("_ollama_backend", ollama_manager)


def ollama_status(force: bool = False) -> dict:
    """Estado del servidor y modelos locales, cacheado unos segundos para no bloquear cada rerun."""
    if config.AI_DISABLED and "_ollama_backend" not in ss:
        return {"t": time.monotonic(), "up": False, "models": [], "disabled": True}
    cached = ss.get("_status")
    if not force and cached and time.monotonic() - cached["t"] < STATUS_TTL_S:
        return cached
    om = backend()
    up = om.is_server_up()
    models = []
    if up:
        try:
            models = om.list_local_models()
        except Exception:
            up = False
    ss["_status"] = {"t": time.monotonic(), "up": up, "models": models}
    return ss["_status"]


def is_local(model: str, models: list[str]) -> bool:
    return model in models or f"{model}:latest" in models


def llm_for(status: dict):
    override = ss.get("_llm_override")
    if override is not None:
        return override
    if not status["up"]:
        def offline(*_a, **_k):
            raise ollama_manager.OllamaUnavailable("Ollama está apagado.")
        return offline
    return backend().chat


def reset_conversation() -> None:
    ss["messages"] = []
    ss["history"] = []


# --- Encabezado: modelo y estado ---------------------------------------------------

status = ollama_status()
options = list(dict.fromkeys(config.SUPPORTED_MODELS + status["models"]))
if ss["active_model"] not in options:
    options.append(ss["active_model"])

st.markdown("## Asistente")
c_model, c_state, c_ai = st.columns([2, 1, 1], vertical_alignment="bottom")
selected = c_model.selectbox("Modelo", options, index=options.index(ss["active_model"]), key="model_select")
c_ai.toggle("Redacción con IA", key="ai_writing", disabled=not status["up"],
            help="Las consultas verificadas responden al instante con una frase calculada. Actívalo "
                 "para que el modelo redacte la respuesta (unos 11 s más por pregunta en CPU).")

def model_loaded(model: str) -> bool:
    """¿Está el modelo cargado en RAM (/api/ps)? Si no se puede saber, se asume que sí."""
    check = getattr(backend(), "is_model_loaded", None)
    if check is None:
        return True
    try:
        return check(model)
    except Exception:
        return True


def is_warming(model: str) -> bool:
    return (status["up"] and not status.get("disabled") and is_local(model, status["models"])
            and not model_loaded(model))


downloading = pull_log.progress(selected, config.LOGS_DIR) is not None
warming = not downloading and is_warming(selected)
if warming:
    # Descargado pero no en RAM: se precalienta en segundo plano (una vez por proceso). Normalmente
    # ya lo lanzó bootstrap.py; esto cubre abrir la app sin él o después de cambiar de modelo.
    getattr(backend(), "start_warm_up", warmup.start_background)(selected)


@st.fragment(run_every=3 if (downloading or warming) else None)
def model_state() -> None:
    """Indicador del modelo; mientras descarga o se carga en RAM se refresca solo."""
    pct = pull_log.progress(selected, config.LOGS_DIR)
    if pct is not None:
        state = f"↓ descargando… {pct:.0f} %"
    elif downloading or (warming and not is_warming(selected)):  # terminó desde el último refresco
        ollama_status(force=True)
        st.rerun(scope="app")
        return
    elif status.get("disabled"):
        state = "○ modo sin IA"
    elif not status["up"]:
        state = "○ Ollama apagado"
    elif not is_local(selected, status["models"]):
        state = "↓ no descargado"
    elif warming:
        state = "◐ cargando…"
    else:
        state = "● listo"
    st.markdown(f"<div class='status-dot'>{state}</div>", unsafe_allow_html=True)


with c_state:
    model_state()

# Cambio de modelo: libera el anterior, descarga el nuevo si hace falta y reinicia la conversación.
if selected != ss["active_model"]:
    previous = ss["active_model"]
    om = backend()
    if status["up"]:
        try:
            om.unload_model(previous)
        except Exception:
            pass
        if not is_local(selected, status["models"]):
            bar = st.progress(0, text=f"Descargando {selected}…")
            try:
                for p in om.pull_model(selected):
                    pct = p.get("percent")
                    if pct is not None:
                        bar.progress(min(int(pct), 100), text=f"Descargando {selected}: {pct:.0f}%")
                bar.empty()
            except Exception as exc:
                bar.empty()
                st.error(f"No se pudo descargar {selected}: {exc}")
        status = ollama_status(force=True)
    ss["active_model"] = selected
    reset_conversation()
    st.toast(f"Modelo {selected} activo; conversación reiniciada")

model = ss["active_model"]

if status.get("disabled"):
    with st.container(border=True):
        st.markdown(
            "**Modo sin IA.** El dashboard y las preguntas sobre las 10 necesidades de negocio "
            "funcionan con consultas verificadas; las preguntas libres necesitan Ollama. Para "
            "activarlo, vuelve a arrancar sin `--sin-ia` (el arranque ofrece instalar Ollama).")
elif not status["up"]:
    with st.container(border=True):
        c_msg, c_btn = st.columns([4, 1], vertical_alignment="center")
        c_msg.markdown(
            "**Ollama está apagado.** Las preguntas sobre las 10 necesidades de negocio se siguen "
            "respondiendo con consultas verificadas; para preguntas libres inicia Ollama.")
        if c_btn.button("Iniciar Ollama", key="start_ollama", width="stretch"):
            with st.spinner("Iniciando Ollama…"):
                ok = backend().try_start_server()
            ollama_status(force=True)
            st.toast("Ollama en ejecución" if ok else "No se pudo iniciar Ollama: ¿está instalado?")
            st.rerun()


# --- Render de mensajes --------------------------------------------------------------

def md_text(text: str) -> str:
    """Escapa "$" para que Streamlit no interprete dos montos como una fórmula LaTeX."""
    return text.replace("$", r"\$")


def render_result(r: se.QueryResult) -> None:
    st.markdown(md_text(r.answer or "Sin respuesta."))
    label, css = SOURCE_BADGES.get(r.source, SOURCE_BADGES["llm"])
    chips = []
    if r.filters.get("store_name"):
        chips.append(f"Tienda: {r.filters['store_name']}")
    if r.filters.get("date_from") or r.filters.get("date_to"):
        chips.append(f"Periodo: {r.filters.get('date_from', '…')} – {r.filters.get('date_to', '…')}")
    for kind, value in r.unsupported_filters:
        chips.append(f"Adaptado por IA: {kind} {value}")
    chips_html = "".join(f"<span class='chip'>{c}</span>" for c in chips)
    st.markdown(f"<span class='badge {css}'>{label}</span>{chips_html}", unsafe_allow_html=True)

    if r.sql:
        with st.expander("SQL"):
            st.code(r.sql, language="sql")
    if r.df is not None and not r.df.empty:
        fig = None
        if r.source == "verificada" and r.business_query_id in charts.NEED_CHARTS:
            fig = charts.NEED_CHARTS[r.business_query_id](r.df)
        else:
            fig = charts.auto_chart(r.df)
        if fig is not None:
            st.plotly_chart(fig, config=charts.CONFIG, width="stretch", key=f"chat_chart_{id(r)}")
        st.dataframe(r.df, hide_index=True, width="stretch", height=min(38 * (len(r.df) + 1) + 3, 320),
                     column_config=charts.column_config(r.df))
    total = sum(r.timings.values())
    engine = "sin LLM" if r.source == "verificada" and total < 1 else r.model
    st.caption(f"{'<0.1' if total < 0.1 else f'{total:.1f}'} s · {engine}")


# --- Entrada (se lee antes de dibujar: si llega una pregunta, no se muestra el saludo) ---

with st.container(key="plus"):
    if st.button("+", key="plus_btn", help="Adjuntar (próximamente)"):
        st.toast("Próximamente")

prompt = st.chat_input("Pregunta sobre ventas, inventario, tiendas…", key="chat_box")
question = prompt or ss.pop("pending", None)
AVATARS = {"user": ":material/person:", "assistant": ":material/pedal_bike:"}

if not ss["messages"] and not question:
    with st.container(border=True):
        st.markdown("**Hola.** Pregúntame por ventas, inventario, tiendas o vendedores de Bike Stores. "
                    "Te respondo con cifras de la base y te muestro la consulta que usé.")
        cols = st.columns(2)
        for i, q in enumerate(SUGGESTIONS):
            if cols[i % 2].button(q, key=f"sugg_{i}", width="stretch"):
                ss["pending"] = q
                st.rerun()

for msg in ss["messages"]:
    with st.chat_message(msg["role"], avatar=AVATARS[msg["role"]]):
        if msg["role"] == "user":
            st.markdown(msg["content"])
        else:
            render_result(msg["result"])


# --- Respuesta a la pregunta nueva ---------------------------------------------------

if question:
    ss["messages"].append({"role": "user", "content": question})
    with st.chat_message("user", avatar=AVATARS["user"]):
        st.markdown(question)
    with st.chat_message("assistant", avatar=AVATARS["assistant"]):
        llm = llm_for(status)
        with st.status("Generando consulta…", expanded=False) as box:
            t0 = time.perf_counter()
            result = se.answer_question(question, model, ss["history"], llm=llm, synthesize_answer=False)
            if result.error is None and result.df is not None:
                t1 = time.perf_counter()
                if result.source == "verificada" and not (ss["ai_writing"] and status["up"]):
                    # Respuesta instantánea con la frase determinística (config.VERIFIED_SYNTHESIS).
                    result.answer = (se.NO_ROWS_ANSWER if result.df.empty
                                     else se.template_answer(result.df, result.business_query_id))
                else:
                    box.update(label="Analizando resultados…")
                    bq_id = result.business_query_id if result.source == "verificada" else None
                    result.answer, _ = se.synthesize(question, result.sql, result.df, model, llm, bq_id)
                result.timings["synth"] = time.perf_counter() - t1
            box.update(label="Listo", state="complete" if result.error is None else "error")
        render_result(result)
    ss["messages"].append({"role": "assistant", "result": result})
    if result.sql and result.error is None:
        ss["history"].append({"question": question, "sql": result.sql})
