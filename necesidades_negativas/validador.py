"""Validador del catálogo: toda SQL (de Claude Code, de un modelo grande o de plantilla) pasa por aquí.

Una entrada es válida si:
  1. es una sola consulta SELECT/WITH (sqlglot, dialecto sqlite) sobre tablas y vistas que existen;
  2. se ejecuta en la conexión de solo lectura con timeout;
  3. devuelve al menos una fila (o declara `espera_vacio: true` y explica el motivo en `notas`);
  4. frente al resultado de la necesidad base, el comparador determinista da lo que corresponde al
     tipo: `igual` para parafrasis/ruido y `distinta` para agregado_distinto, casi_igual_trampa y
     filtro_distinto (si una trampa da igual, no enseña nada: se corrige o se descarta).
     Se puede fijar con `comparador_esperado` ("igual" | "distinta" | "n/a"); `ambigua` es "n/a".

El veredicto lo da eval_text2sql.compare_results (determinista); ningún LLM interviene aquí.
"""

from __future__ import annotations

import re
from pathlib import Path

import config
import db
import sql_engine as se
from business_queries import BY_ID, render_sql

from . import catalogo

EXPECTED = {"parafrasis": "igual", "ruido": "igual", "agregado_distinto": "distinta",
            "casi_igual_trampa": "distinta", "filtro_distinto": "distinta", "ambigua": "n/a"}
_SELECT_ONLY = re.compile(r"^\s*(?:\(\s*)*(select|with)\b", re.IGNORECASE)


def _golden_checks() -> dict[str, dict]:
    import eval_text2sql as ev
    return {it["business_query"]: it["check"] for it in ev.load_golden()
            if it.get("business_query") and it["nivel"] == "negocio"}


def base_reference(need: str, db_path: Path = config.DB_PATH, _cache: dict | None = None):
    """(DataFrame de la necesidad base sin filtros, criterio de comparación del golden set)."""
    cache = _cache if _cache is not None else {}
    if need not in cache:
        sql = render_sql(BY_ID[need])
        cache[need] = (se.execute_sql(se.validate_sql(sql, db_path), db_path),
                       _golden_checks().get(need, {"mode": "exact"}))
    return cache[need]


def validate_entry(entry: dict, db_path: Path = config.DB_PATH, base_cache: dict | None = None
                   ) -> tuple[dict, list[str]]:
    """Devuelve (bloque `validacion`, lista de problemas). Lista vacía = válida."""
    import eval_text2sql as ev
    problems: list[str] = []
    v = {"ejecuta": False, "filas": 0, "sqlglot_ok": False, "solo_select": False,
         "comparador_vs_base": "n/a"}
    tipo, need, sql = entry.get("tipo"), entry.get("necesidad_base"), entry.get("sql") or ""
    if tipo not in catalogo.TIPOS:
        problems.append(f"tipo desconocido: {tipo!r}")
    if need not in BY_ID:
        problems.append(f"necesidad_base desconocida: {need!r}")
    if not str(entry.get("pregunta", "")).strip():
        problems.append("pregunta vacía")
    if entry.get("resuelto_por") not in catalogo.RESUELTO_POR:
        problems.append(f"resuelto_por inválido: {entry.get('resuelto_por')!r}")

    v["solo_select"] = bool(_SELECT_ONLY.match(sql))
    final_sql = None
    try:
        final_sql = se.validate_sql(sql, db_path)    # sqlglot, un solo statement, solo lectura
        v["sqlglot_ok"] = True
    except se.SQLValidationError as exc:
        problems.append(f"SQL no válida: {exc}")
        v["solo_select"] = v["solo_select"] and "no permitida" not in str(exc).lower()
    if not v["solo_select"]:
        problems.append("no es una consulta SELECT/WITH")

    df = None
    if final_sql:
        try:
            df = db.run_query(final_sql, None, db_path, se.QUERY_TIMEOUT_S)   # conexión mode=ro
            v["ejecuta"], v["filas"] = True, len(df)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo de ejecución invalida
            problems.append(f"no ejecuta: {str(exc).rsplit(chr(39) + ': ', 1)[-1][:120]}")
    if df is not None and df.empty and not (entry.get("espera_vacio") and str(entry.get("notas", "")).strip()):
        problems.append("0 filas (usa espera_vacio:true y explica el motivo en notas)")

    expected = entry.get("comparador_esperado") or EXPECTED.get(tipo, "n/a")
    if df is not None and need in BY_ID and not df.empty:
        base_df, check = base_reference(need, db_path, base_cache)
        same, reason = ev.compare_results(base_df, df, check)
        if expected == "n/a":
            v["comparador_vs_base"] = "igual" if same else "n/a"
        elif same and expected == "igual":
            v["comparador_vs_base"] = "igual"
        elif not same and expected == "distinta":
            v["comparador_vs_base"] = "distinta_a_proposito"
        else:
            v["comparador_vs_base"] = "igual" if same else "distinta_a_proposito"
            problems.append(f"el comparador dio {'igual' if same else 'distinta'} y se esperaba "
                            f"{expected} para tipo {tipo} ({reason[:80]})")
    return v, problems


def validate_catalog(rows: list[dict], db_path: Path = config.DB_PATH) -> list[tuple[str, list[str]]]:
    """Revalida todo el catálogo y revisa duplicados, ids, split. Devuelve [(id, problemas)] de los malos."""
    bad: list[tuple[str, list[str]]] = []
    seen_ids, seen_q = set(), {}
    cache: dict = {}
    for row in rows:
        problems = []
        if row.get("id") in seen_ids:
            problems.append("id duplicado")
        seen_ids.add(row.get("id"))
        nq = catalogo.normalize_question(row.get("pregunta", ""))
        if nq in seen_q:
            problems.append(f"pregunta duplicada de {seen_q[nq]}")
        seen_q.setdefault(nq, row.get("id"))
        if row.get("split") != catalogo.split_for(row.get("id", "")):
            problems.append("split no coincide con el hash del id")
        if not row.get("validado"):
            problems.append("validado:false")
        _, found = validate_entry(row, db_path, cache)
        problems += found
        if problems:
            bad.append((row.get("id", "?"), problems))
    return bad
