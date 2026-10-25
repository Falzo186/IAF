"""Página Asistente: chat Text-to-SQL con modelos locales de Ollama.

Para las pruebas se pueden inyectar en st.session_state:
    _llm_override     callable(model, messages, **options) -> str
    _ollama_backend   objeto con la interfaz de ollama_manager
"""

import time

import pandas as pd
import streamlit as st
import yaml

import bridge
import config
import learned_patterns
import netmode
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
ss.setdefault("judge_mode", False)   # "Verificar con juez": apagado = chat de siempre
ss.setdefault("context_mode", "Base")        # fase 11: Base = el prompt de siempre
ss.setdefault("net_mode", "Local offline")   # fase 11: offline = ninguna conexión hacia fuera

SOURCE_BADGES = {
    "verificada": ("Verificada", "badge-verificada"),
    "llm_anclada": ("IA anclada", "badge-anclada"),
    "llm": ("Generada por IA", "badge-llm"),
    "solo_lectura": ("Solo lectura", "badge-anclada"),
    "llm_ejemplos": ("IA + ejemplos", "badge-ejemplos"),
    "llm_grande": ("Generada por modelo grande (online)", "badge-grande"),
}
CONTEXT_MODES = {"Base": "base", "Few shot": "fewshot", "RAG": "rag", "Harness": "harness"}
NET_MODES = {"Local offline": "offline", "Online gratis": "online"}
SUGGESTIONS = [
    "¿Qué productos se venden mucho pero están a punto de agotarse?",
    "¿Cuánto dinero perdimos por pedidos rechazados?",
    "Ticket promedio por tienda en 2017",
    "¿Cuáles son las 5 marcas con más unidades vendidas?",
]
STATUS_TTL_S = 10
JUDGE_MAX_ATTEMPTS = 3
SAME_MODEL = "Mismo modelo"
# Accesos directos: etiqueta corta de cada necesidad. La pregunta que envían es la canónica de
# reference_answers.yaml, que el enrutador resuelve siempre con la consulta verificada.
NEED_SHORTCUTS = [
    ("N1", "Rentabilidad"), ("N2", "Quiebre de stock"), ("N3", "Electric Bikes"),
    ("N4", "Ciudades premium"), ("N5", "Envíos tarde"), ("N6", "Inventario inactivo"),
    ("N7", "Multimarca"), ("N8", "Ticket promedio"), ("N9", "Rotación"), ("N10", "Cancelaciones"),
]


@st.cache_data(show_spinner=False)
def canonical_questions() -> dict[str, str]:
    data = yaml.safe_load((config.BASE_DIR / "reference_answers.yaml").read_text(encoding="utf-8"))
    return {need: data[need]["pregunta"] for need, _ in NEED_SHORTCUTS}


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
# Solo los 3 modelos soportados, aunque haya otros instalados (qwen3:4b, 7B…): nunca se ofrecen.
# Si uno no está descargado se lista igual y el indicador dice "↓ no descargado".
options = list(config.SUPPORTED_MODELS)
if ss["active_model"] not in options:
    ss["active_model"] = config.DEFAULT_MODEL

st.markdown("## Asistente")
c_model, c_state, c_ai, c_judge = st.columns([2, 1, 1, 1], vertical_alignment="bottom")
selected = c_model.selectbox("Modelo", options, index=options.index(ss["active_model"]), key="model_select")
c_ai.toggle("Redacción con IA", key="ai_writing", disabled=not status["up"],
            help="Las consultas verificadas responden al instante con una frase calculada. Actívalo "
                 "para que el modelo redacte la respuesta (unos 11 s más por pregunta en CPU).")
c_judge.toggle("Verificar con juez", key="judge_mode", disabled=not status["up"],
               help="Más lento, pero muestra cómo el modelo corrige sus propios errores con ayuda "
                    "de un juez.")
judge_on = ss["judge_mode"] and status["up"]
if judge_on:
    # Por omisión el juez es el mismo modelo ya cargado (una sola carga en RAM, otro rol).
    st.columns([2, 3])[0].selectbox(
        "Modelo juez", [SAME_MODEL] + config.SUPPORTED_MODELS, key="judge_model",
        help="Otro modelo como juez implica cargar dos modelos a la vez (más RAM).")

# --- Configuración avanzada (fase 11): contexto y modo de red -------------------------------

with st.expander("Configuración avanzada", expanded=False):
    c_ctx, c_net = st.columns(2)
    c_ctx.selectbox(
        "Modo de contexto", list(CONTEXT_MODES), key="context_mode",
        help="Base: el prompt de siempre. Few shot: añade ejemplos resueltos parecidos. RAG: ejemplos "
             "sobre un umbral y esquema recortado. Harness: RAG + validación de columnas + reparación.")
    c_net.radio(
        "Modo de red", list(NET_MODES), key="net_mode", horizontal=True,
        help="Local offline (por defecto): no se abre ninguna conexión hacia fuera, solo Ollama en "
             "localhost. Online gratis: permite escalar al puente de un modelo grande de capa gratuita "
             "cuando el local no logra una consulta; requiere llave (ver .env.example).")

# El modo de red se aplica en cada ejecución (la app es de un solo usuario local).
netmode.set_mode(NET_MODES[ss["net_mode"]])
config.BRIDGE_ENABLED = ss["net_mode"] == "Online gratis"
context_mode = CONTEXT_MODES[ss["context_mode"]]
online = netmode.is_online()
bridge_now = bridge.get_bridge() if online else None
if online and not bridge_now.available():
    st.caption(f"Puente online no disponible ({bridge_now.reason}); se sigue en local.")
st.markdown(
    "<span class='badge badge-online'>ONLINE gratis · puente opcional</span>" if online
    else "<span class='badge badge-offline'>OFFLINE · sin red</span>", unsafe_allow_html=True)


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


# --- Accesos directos a las 10 necesidades (1 clic = pregunta canónica) ----------------

with st.container(horizontal=True, key="needs", gap="small"):
    questions = canonical_questions()
    for need, label in NEED_SHORTCUTS:
        if st.button(f"{need} {label}", key=f"need_{need}", help=questions[need]):
            ss["pending"] = questions[need]
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
    if r.reference_id:
        chips.append(f"Comparada con la consulta verificada {r.reference_id}: "
                     + ("coincide" if r.reference_match else "no coincide"))
    elif r.judge_model and r.source in ("llm", "llm_ejemplos"):
        chips.append("Revisada por el juez, sin respuesta de referencia")
    if r.modo_contexto != "base":
        chips.append(f"Contexto: {r.modo_contexto}")
    chips_html = "".join(f"<span class='chip'>{c}</span>" for c in chips)
    st.markdown(f"<span class='badge {css}'>{label}</span>{chips_html}", unsafe_allow_html=True)

    if r.sql:
        with st.expander("SQL"):
            st.code(r.sql, language="sql")
    render_attempts(r.intentos)
    render_retrieval(r)
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
    engine = "sin LLM" if r.source in ("verificada", "solo_lectura") and total < 1 else r.model
    if r.judge_model and r.judge_model != r.model:
        engine += f" · juez {r.judge_model}"
    caption = f"{fmt_s(total)} s · {engine}"
    if r.intentos:
        n = len(r.intentos)
        caption += (f" · {n} {'intento' if n == 1 else 'intentos'}: "
                    f"{fmt_s(sum(i['tiempo_segundos'] for i in r.intentos))} s")
    st.caption(caption)


def fmt_s(seconds: float) -> str:
    return "<0.1" if seconds < 0.1 else f"{seconds:.1f}"


def attempt_outcome(i: dict) -> str:
    """Resultado de un intento, sin interpretar: lo decidió el comparador, la ejecución o nadie."""
    if i["exito"] is None:
        return "○ se ejecutó (sin referencia para comprobarlo)"
    if not i["exito"]:
        return "✗ falló"
    return "✓ acertó" if i["criterio"] in ("verificada", "comparador") else "✓ se ejecutó"


def attempt_line(i: dict) -> str:
    line = f"**Intento {i['numero']}** — {attempt_outcome(i)} ({fmt_s(i['tiempo_segundos'])} s)"
    if i["diagnostico"]:
        kind = "comentario del juez" if i["exito"] is None else "diagnóstico"
        line += f" — {kind}: “{md_text(i['diagnostico'])}”"
    return line


def trace_line(t: dict) -> str:
    """Una etapa del harness en una línea legible (sin SQL)."""
    stage = t["etapa"]
    if stage == "ruteo":
        return f"**Ruteo** — {t['resultado']}{'' if t.get('usa_llm') else ' (sin LLM)'}"
    if stage == "recuperacion":
        n = len(t.get("ejemplos", []))
        extra = f", umbral {t['umbral']}" if "umbral" in t else ""
        recorte = ", esquema recortado" if t.get("esquema_recortado") else ""
        return f"**Recuperación** — {t['modo']}: {n} ejemplo(s){extra}{recorte}" + (f" ({t['nota']})" if t.get("nota") else "")
    if stage == "generacion":
        return (f"**Generación** — {t['modelo']}, {t['intentos']} intento(s), validación estática de "
                f"{t['validacion_estatica']}, reparación con {t['reparacion']}: {'ok' if t['ok'] else 'sin resultado'}")
    if stage == "consistencia":
        return f"**Consistencia** — {t['muestras']} muestras, ganó el resultado con {t['votos_ganador']} votos"
    if stage == "escalamiento":
        detail = t.get("motivo") or t.get("proveedor", "")
        return f"**Escalamiento** — {t['estado']}" + (f": {detail}" if detail else "")
    return f"**{stage}**"


def render_retrieval(r: se.QueryResult) -> None:
    """Ejemplos recuperados (pregunta y puntaje, nunca su SQL) y traza del harness."""
    if r.ejemplos:
        with st.expander(f"Ejemplos recuperados ({len(r.ejemplos)})"):
            for e in r.ejemplos:
                score = "" if e.get("score") is None else f" · puntaje {e['score']:.2f}"
                st.markdown(f"- “{md_text(e['pregunta'])}” ({e['origen']}{score})")
    if r.modo_contexto == "harness" and r.traza:
        with st.expander("Traza del harness"):
            for t in r.traza:
                st.markdown("- " + md_text(trace_line(t)))


def render_attempts(intentos: list[dict]) -> None:
    """Expander "Intentos (N)": cada intento en orden, con el diagnóstico literal de los fallidos."""
    if not intentos:
        return
    if len(intentos) == 1:
        # Caso normal: se muestra directo, sin colapsar (un expander no conserva expanded=True al
        # volver a dibujar el historial).
        first = intentos[0]
        verb = attempt_outcome(first).split(" ", 1)[1].split(" (")[0]
        label = f"Intentos (1) — {verb} a la primera" if first["exito"] is not False else "Intentos (1) — falló"
        with st.container(border=True, key=f"intentos_{id(intentos)}"):
            st.markdown(f"<div class='attempts-title'>{label}</div>", unsafe_allow_html=True)
            st.markdown(attempt_line(first))
        return
    with st.expander(f"Intentos ({len(intentos)})"):
        for i in intentos:
            st.markdown(attempt_line(i))


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
        label = (f"Generando y revisando la consulta (hasta {JUDGE_MAX_ATTEMPTS} intentos)…"
                 if judge_on else "Generando consulta…")
        with st.status(label, expanded=False) as box:
            t0 = time.perf_counter()
            if judge_on:
                # Modo juez: el modelo contesta solo con el esquema, aun en las 10 necesidades; si la
                # pregunta es una de ellas, su consulta verificada es la referencia del comparador.
                route, bq, params, _ = se.plan_route(question)
                ref = se.reference_for(bq, params) if route == "verificada" else None
                judge_model = ss.get("judge_model", SAME_MODEL)
                # Con referencia, el modelo no puede ver su SQL ni las de la misma necesidad en los ejemplos.
                opts = ({"exclude_sql": [ref.sql], "exclude_ids": [ref.need_id], "exclude_need": ref.need_id}
                        if ref else None)
                result = se.answer_with_judge(
                    question, model, None if judge_model == SAME_MODEL else judge_model, ref,
                    JUDGE_MAX_ATTEMPTS, history=ss["history"], llm=llm,
                    modo_contexto=context_mode, contexto_opts=opts)
            else:
                result = se.answer_question(
                    question, model, ss["history"], llm=llm, synthesize_answer=False,
                    modo_contexto=context_mode,
                    contexto_opts={"escalar": bool(online and bridge_now and bridge_now.available())})
            learned_patterns.log_pattern(result)  # bitácora para revisión humana; no afecta la respuesta
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
