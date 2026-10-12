"""Feedback para el siguiente intento de SQL según la categoría de falla (fase 7).

Regla: el feedback describe la FORMA del problema, nunca el valor correcto. Salvo en los
errores de ejecución (donde se devuelve el mensaje real de SQLite o del validador, que solo
habla de la SQL del propio modelo), los mensajes no contienen dígitos ni ningún texto de la
referencia: ni cifras, ni nombres, ni el número de filas esperado.
"""

from __future__ import annotations

import re

import pandas as pd

ERROR_CATEGORIES = {"error_ejecucion", "tabla_columna_inexistente"}

GENERIC = ("El resultado no responde a la pregunta. Revísala paso a paso: qué vista o tabla "
           "usas, qué filtros aplicas en el WHERE, cómo agregas y si ordenas o limitas lo que pide.")


def _rows_word(n: int) -> str:
    return "ninguna fila" if n == 0 else ("una sola fila" if n == 1 else "varias filas")


def feedback_for(category: str, *, error: str | None = None, got: pd.DataFrame | None = None,
                 ref_rows: int | None = None, ref_cols: int | None = None,
                 agg_differs: bool = False, filter_kinds: set[str] | None = None) -> str:
    """Mensaje para el siguiente intento.

    ref_rows/ref_cols solo se usan para COMPARAR (más o menos filas o columnas que la
    referencia); el mensaje nunca dice cuántas son.
    """
    if category in ERROR_CATEGORIES:
        return error or GENERIC
    if category == "agregacion_incorrecta":
        parts = []
        if got is not None and ref_rows is not None:
            if len(got) < ref_rows:
                parts.append(f"Tu resultado tiene {_rows_word(len(got))}, pero la pregunta pide un "
                             "desglose: probablemente falta un GROUP BY por la dimensión que se pide "
                             "(tienda, mes, categoría, producto…).")
            elif len(got) > ref_rows:
                parts.append("Tu resultado tiene más filas de las que pide la pregunta: revisa si "
                             "agrupas por una columna de más, si falta un filtro o si falta un LIMIT.")
        if got is not None and ref_cols is not None and got.shape[1] < ref_cols:
            parts.append("A tu resultado le faltan columnas que la pregunta pide: incluye la "
                         "dimensión y la métrica que se preguntan.")
        if agg_differs or not parts:
            parts.append("Revisa la función de agregación: si la pregunta es por orden (ticket, "
                         "órdenes), agrega por orden (v_orders o COUNT(DISTINCT order_id)) y no por "
                         "línea de pedido; comprueba también si corresponde SUM, AVG o COUNT.")
        return " ".join(parts)
    if category == "filtro_incorrecto":
        kinds = filter_kinds or set()
        names = []
        if "estado" in kinds:
            names.append("el filtro de estado de la orden (order_status)")
        if "fecha" in kinds:
            names.append("el filtro de fechas o periodo")
        if "texto" in kinds:
            names.append("los nombres que comparas (tienda, categoría, marca, estado…)")
        target = ", ".join(names) if names else "las condiciones del WHERE"
        return (f"Revisa {target}: compara cada condición con lo que pide la pregunta y con los "
                "valores válidos del esquema.")
    return GENERIC


def filter_kinds(ref_signature: set[str], got_signature: set[str]) -> set[str]:
    """Tipos de filtro que difieren ("estado", "fecha", "texto"), sin sus valores."""
    return {item.split("=", 1)[0] for item in ref_signature ^ got_signature}


def has_digits(text: str) -> bool:
    return bool(re.search(r"\d", text))
