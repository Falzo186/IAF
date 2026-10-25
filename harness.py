"""Harness (fase 11): pipeline determinista con etapas trazadas. Orquesta, no duplica.

    1. ruteo        consulta verificada (N1-N10) si la pregunta la reconoce -> sin LLM
    2. recuperación RAG + few-shot dinámico (context_modes.prepare)
    3. generación   modelo local elegido (answer_question)
    4. validación   estática: sqlglot, solo SELECT, tablas y columnas que existen (columnas inventadas)
    5. ejecución    conexión de solo lectura, timeout, LIMIT de seguridad (sql_engine)
    6. reparación   hasta max_intentos con el error de SQLite/validación (sin SQL de referencia ni cifras)
    7. consistencia opcional: N muestras, voto por el resultado más frecuente
    8. escalamiento opcional al puente (solo modo online y si el local no logró nada útil)
    9. salida       QueryResult con `fuente` y `traza`

Los criterios de reparación y escalamiento solo usan lo que ve el sistema (errores, filas vacías):
nunca la referencia de la pregunta evaluada.
"""

from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path

import sqlglot
from sqlglot import exp

import config
import netmode
import sql_engine as se

CONSISTENCY_OPTIONS = {**se.SQL_OPTIONS, "temperature": 0.4}


# ---------------------------------------------------------------------------
# Validación estática: columnas inventadas
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _real_columns(db_path: str) -> dict[str, tuple[str, ...]]:
    conn = se._ro_connect(Path(db_path))
    try:
        out = {}
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall():
            out[name.lower()] = tuple(r[1].lower() for r in conn.execute(f"PRAGMA table_info({name})"))
        return out
    finally:
        conn.close()


def check_columns(sql: str, db_path: Path = config.DB_PATH) -> str | None:
    """Mensaje si la SQL usa una columna que no existe en las tablas que consulta; None si está bien.

    Es conservadora: ignora alias de SELECT, columnas de CTE/subconsultas y nombres entre comillas,
    para no inventar errores donde SQLite no los daría.
    """
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except sqlglot.errors.SqlglotError:
        return None                                    # de eso se encarga validate_sql
    real = _real_columns(str(Path(db_path).resolve()))
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    derived = {s.alias.lower() for s in tree.find_all(exp.Subquery) if s.alias}
    allowed = {a.alias.lower() for a in tree.find_all(exp.Alias) if a.alias}     # alias de SELECT
    for cte in tree.find_all(exp.CTE):
        for sel in cte.find_all(exp.Select):
            allowed |= {e.alias_or_name.lower() for e in sel.expressions if e.alias_or_name}
    alias_map, used = {}, []
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        if name in real:
            alias_map[(t.alias or t.name).lower()] = name
            alias_map[name] = name
            if name not in used:
                used.append(name)
    has_nested = bool(ctes or derived)

    for col in tree.find_all(exp.Column):
        name = col.name.lower()
        ident = col.this
        if not name or isinstance(col.this, exp.Star) or getattr(ident, "quoted", False):
            continue
        if name in allowed:
            continue
        qualifier = col.table.lower() if col.table else ""
        if qualifier:
            table = alias_map.get(qualifier)
            if table and name not in real[table]:
                return (f"La columna '{col.name}' no existe en '{table}'. "
                        f"Columnas de {table}: {', '.join(real[table])}.")
            continue
        if not used:
            continue
        if has_nested:
            if not any(name in real[t] for t in used) and name not in allowed:
                return (f"La columna '{col.name}' no existe en las tablas que consultas "
                        f"({', '.join(used)}). Usa solo columnas del esquema.")
        elif not any(name in real[t] for t in used):
            if len(used) == 1:
                return (f"La columna '{col.name}' no existe en '{used[0]}'. "
                        f"Columnas de {used[0]}: {', '.join(real[used[0]])}.")
            return (f"La columna '{col.name}' no existe en ninguna de las tablas que consultas "
                    f"({', '.join(used)}). Usa solo columnas del esquema.")
    return None


def make_sql_check(db_path: Path = config.DB_PATH):
    return lambda sql: check_columns(sql, db_path)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _fingerprint(result: se.QueryResult) -> str:
    import eval_text2sql as ev
    return ev.result_fingerprint(result.df, result.error)


def _escalate(result: se.QueryResult, question: str, history, db_path: Path, bridge, traza: list) -> bool:
    """Pide la SQL al modelo grande y la valida como cualquier otra. True si quedó resuelto."""
    import bridge as bridge_mod
    if bridge is None:
        bridge = bridge_mod.get_bridge()
    if not bridge.available():
        traza.append({"etapa": "escalamiento", "estado": "omitido",
                      "motivo": getattr(bridge, "reason", "puente no disponible"), "modo_red": netmode.get_mode()})
        return False
    t0 = time.perf_counter()
    messages = se.build_sql_messages(question, history if se.is_follow_up(question) else None, db_path)
    sql, why = bridge_mod.generate_sql(bridge, messages)
    if not sql:
        traza.append({"etapa": "escalamiento", "estado": "sin_sql", "motivo": why})
        return False
    try:
        final_sql, df, exec_t = se._run_sql(sql, db_path)      # misma validación y solo lectura
    except (se.SQLValidationError, se.QueryTimeout, se.sqlite3.Error, se.pd.errors.DatabaseError) as exc:
        traza.append({"etapa": "escalamiento", "estado": "sql_rechazada", "motivo": str(exc)[:160]})
        return False
    result.sql, result.df, result.error, result.answer = final_sql, df, None, ""
    result.source = "llm_grande"
    result.intentos.append(se._intento(len(result.intentos) + 1, final_sql, True, time.perf_counter() - t0,
                                       None, f"puente:{bridge.name}"))
    traza.append({"etapa": "escalamiento", "estado": "resuelto", "proveedor": bridge.name,
                  "modelo": getattr(bridge, "model", ""), "detalle": why})
    return True


def run(question: str, model: str, history=None, llm=None, *, db_path: Path = config.DB_PATH,
        use_router: bool = False, synthesize_answer: bool = False, max_attempts: int | None = None,
        attempt_check=None, contexto_opts: dict | None = None, consistencia: int = 1,
        escalar: bool = False, bridge=None) -> se.QueryResult:
    """Responde con el harness completo. Nunca lanza excepciones (como answer_question)."""
    t_total = time.perf_counter()
    opts = dict(contexto_opts or {})
    traza: list[dict] = []
    common = dict(db_path=db_path, use_router=use_router, synthesize_answer=synthesize_answer,
                  max_attempts=max_attempts, attempt_check=attempt_check, modo_contexto="harness",
                  contexto_opts=opts, sql_check=make_sql_check(db_path), _desde_harness=True)

    result = se.answer_question(question, model, history, llm, **common)
    result.modo_contexto, result.modo_red = "harness", netmode.get_mode()
    traza.append({"etapa": "ruteo", "resultado": result.source if result.source != "llm_ejemplos" else "llm",
                  "usa_llm": result.source != "verificada"})
    traza.extend(result.traza)
    traza.append({"etapa": "generacion", "modelo": model, "intentos": len(result.intentos),
                  "validacion_estatica": "columnas", "reparacion": "error de SQLite/validación",
                  "ok": result.error is None})

    if result.source != "verificada" and consistencia > 1 and result.error is None:
        runs = [result]
        for _ in range(consistencia - 1):
            extra = se.answer_question(question, model, history, llm, **{**common, "sql_options": CONSISTENCY_OPTIONS,
                                                                           "attempt_check": None, "max_attempts": 1})
            if extra.error is None:
                runs.append(extra)
        prints = [_fingerprint(r) for r in runs]
        modal = max(dict.fromkeys(prints), key=prints.count)
        result = runs[prints.index(modal)]
        result.modo_contexto, result.modo_red = "harness", netmode.get_mode()
        traza.append({"etapa": "consistencia", "muestras": len(runs), "votos_ganador": prints.count(modal)})

    if escalar and result.source != "verificada":
        weak = result.error is not None or (result.df is not None and result.df.empty)
        if weak:
            _escalate(result, question, history, Path(db_path), bridge, traza)
            if result.source == "llm_grande" and synthesize_answer and llm is not None:
                result.answer, _ = se.synthesize(question, result.sql, result.df, model, llm, None)

    result.traza = traza
    result.timings["harness"] = time.perf_counter() - t_total
    return result
