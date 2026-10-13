"""Juez-LLM: SOLO redacta por qué un intento no coincide con la referencia.

El veredicto correcto/incorrecto lo da SIEMPRE el comparador determinista de
eval_text2sql.compare_results. Este módulo no devuelve ningún booleano ni se consulta para
decidir nada: su texto se guarda como `explicacion_juez` para lectura humana del reporte.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

import sql_engine as se

JUDGE_SYSTEM = (
    "Eres un revisor de consultas SQL sobre la base Bike Stores. Ya se determinó, de forma "
    "automática, que el resultado obtenido NO coincide con el de referencia; tu tarea no es "
    "juzgarlo, solo explicar por qué. Responde en 1 o 2 frases, en español, de forma concreta "
    "(tabla o vista usada, filtros, agregación, columnas o top-N). No escribas SQL."
)
JUDGE_OPTIONS = {"temperature": 0.0, "num_predict": 120}
THINKING_OPTIONS = {"temperature": 0.0, "num_predict": 1500}


def _table(df: pd.DataFrame | None, rows: int = 8) -> str:
    if df is None:
        return "(la consulta no se ejecutó)"
    if df.empty:
        return "(0 filas)"
    return se.df_to_markdown(df, rows) + f"\n({len(df)} filas en total)"


def explain_failure(pregunta: str, sql_generada: str | None, resultado: pd.DataFrame | None,
                    referencia: pd.DataFrame, modelo: str, llm=None) -> str:
    """Explicación de 1-2 frases. Nunca lanza excepciones; si el LLM falla devuelve un aviso."""
    llm = llm or se._default_llm()
    user = (f"Pregunta: {pregunta}\n\nSQL generada:\n{sql_generada or '(ninguna)'}\n\n"
            f"Resultado obtenido:\n{_table(resultado)}\n\nResultado de referencia:\n{_table(referencia)}\n\n"
            "¿Por qué no coinciden?")
    messages = [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}]
    try:
        raw = llm(modelo, messages, **JUDGE_OPTIONS) or ""
        text = _strip_think(raw)
        if not text:
            # Modelos de razonamiento (deepseek-r1) gastan el presupuesto pensando (Ollama separa ese
            # razonamiento y el contenido llega vacío): un reintento con más tokens.
            text = _strip_think(llm(modelo, messages, **THINKING_OPTIONS) or "")
    except Exception as exc:  # noqa: BLE001 - el juez es opcional
        return f"(sin explicación: {exc})"
    return text or "(sin explicación)"


def _strip_think(text: str) -> str:
    text = se._THINK_RE.sub("", text)
    if "<think>" in text:          # bloque de razonamiento sin cerrar: no hay explicación
        text = text.split("<think>", 1)[0]
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Crítica en vivo (modo "Verificar con juez" del Asistente)
# ---------------------------------------------------------------------------

CRITIC_SYSTEM = (
    "Eres un revisor experto en SQL (SQLite) de la base Bike Stores. Revisas la consulta que "
    "escribió otro modelo para una pregunta de negocio; tu crítica se le enviará para que la "
    "corrija. Responde en 1 a 3 frases, en español, diciendo en prosa QUÉ está mal y qué cambiar: "
    "columna que no existe, vista o tabla, JOIN, filtro, nivel de agregación, columnas, orden o "
    "límite. NUNCA escribas un bloque de código ni una consulta SQL, ni completa ni corregida, ni "
    "fragmentos que empiecen con SELECT: el otro modelo debe escribir la corrección. No escribas "
    "cifras ni resultados.\n\n"
    "Reglas de buen SQL en esta base: las ventas están en v_order_lines (una fila por línea) y "
    "v_orders (una fila por orden); cuenta solo órdenes completadas (order_status = 4) salvo que "
    "la pregunta pida otro estado; los montos por orden se calculan en v_orders o con "
    "COUNT(DISTINCT order_id); usa solo columnas que existan; agrupa por la dimensión que pide la "
    "pregunta; un ranking necesita ORDER BY y LIMIT.\n\n"
    "Consultas de un experto para otras necesidades del negocio (úsalas como ejemplo de estilo y "
    "de columnas, no como respuesta):\n{ejemplos}"
)
CRITIC_WITH_REFERENCE = ("Ya se comprobó automáticamente que el resultado NO responde bien la "
                         "pregunta. Explica qué cambiar en la consulta.")
CRITIC_WITHOUT_REFERENCE = ("No hay una respuesta conocida para esta pregunta: no digas si es "
                            "correcta o no. Revisa solo si tiene sentido: columnas que existen, "
                            "JOINs coherentes con la pregunta y agregación del nivel correcto.")
CRITIC_OPTIONS = {"temperature": 0.0, "num_predict": 150}
ANSWERS_PATH = se.config.BASE_DIR / "reference_answers.yaml"


def _first_sentence(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text.split(". ")[0].rstrip(".") + "." if text else ""


@lru_cache(maxsize=16)
def needs_context(exclude_need: str | None = None) -> str:
    """Las 10 necesidades con pregunta, SQL verificada y la primera frase de su respuesta de
    referencia, SIN la necesidad `exclude_need` (la que se está respondiendo: sería hacer trampa).
    Solo la primera frase de la respuesta, para que todo quepa en el contexto de 4096 tokens."""
    import yaml
    from business_queries import BUSINESS_QUERIES, render_sql
    try:
        answers = yaml.safe_load(ANSWERS_PATH.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - sin el YAML el juez sigue con pregunta y SQL
        answers = {}
    parts = []
    for bq in BUSINESS_QUERIES:
        if bq.id == exclude_need:
            continue
        a = answers.get(bq.id) or {}
        parts.append(f"### {bq.id}: {bq.titulo}\nPregunta: {a.get('pregunta', bq.titulo)}\n"
                     f"```sql\n{render_sql(bq).strip()}\n```\n"
                     f"Respuesta: {_first_sentence(a.get('respuesta_referencia', ''))}")
    return "\n\n".join(parts)


def critique(pregunta: str, sql_generada: str | None, resultado: pd.DataFrame | None,
             error: str | None, modelo: str, llm=None, exclude_need: str | None = None,
             con_referencia: bool = True) -> str:
    """Crítica en palabras para el siguiente intento. Nunca decide si acertó ni lanza excepciones.
    Quien llama debe sanear el texto (feedback.sanitize) si hay una referencia."""
    llm = llm or se._default_llm()
    obtained = f"Error al ejecutarla: {error}" if error else _table(resultado, 5)
    user = (f"Pregunta: {pregunta}\n\nSQL generada:\n{sql_generada or '(ninguna)'}\n\n"
            f"Resultado:\n{obtained}\n\n"
            + (CRITIC_WITH_REFERENCE if con_referencia else CRITIC_WITHOUT_REFERENCE))
    messages = [{"role": "system", "content": CRITIC_SYSTEM.format(ejemplos=needs_context(exclude_need))},
                {"role": "user", "content": user}]
    try:
        text = _strip_think(llm(modelo, messages, **CRITIC_OPTIONS) or "")
    except Exception:  # noqa: BLE001 - sin crítica, el siguiente intento usa el feedback básico
        return ""
    return text
