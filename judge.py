"""Juez-LLM: SOLO redacta por qué un intento no coincide con la referencia.

El veredicto correcto/incorrecto lo da SIEMPRE el comparador determinista de
eval_text2sql.compare_results. Este módulo no devuelve ningún booleano ni se consulta para
decidir nada: su texto se guarda como `explicacion_juez` para lectura humana del reporte.
"""

from __future__ import annotations

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
