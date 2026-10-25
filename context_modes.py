"""Arma el contexto extra del prompt según el modo (fase 11): "base" | "fewshot" | "rag" | "harness".

Devuelve (prompt_extra, ejemplos, etapa_de_traza):
  prompt_extra  {"examples": texto, "schema": esquema recortado} para sql_engine.build_system_prompt
                ({} en modo base o cuando no hay nada que inyectar: el prompt queda idéntico al de siempre)
  ejemplos      [{id, pregunta, score, origen}] realmente inyectados (para mostrarlos y registrarlos)
  etapa         dict de la traza: qué se recuperó, con qué puntaje y por qué

Opciones (contexto_opts): k, fewshot_modo ("dinamico"|"estatico"), min_score, y las exclusiones de la
evaluación (exclude_ids, exclude_questions, exclude_sql, exclude_need). Producción no pasa ninguna.
"""

from __future__ import annotations

from pathlib import Path

import config
import fewshot
import rag
import sql_engine as se

EXCLUSIONES = ("exclude_ids", "exclude_questions", "exclude_sql", "exclude_need")


def _exclusions(opts: dict) -> dict:
    return {k: opts[k] for k in EXCLUSIONES if k in opts}


def _origin(ex: dict) -> str:
    return ex.get("origen") or ("catalogo" if ex.get("tipo") not in ("verificada", "patron") else ex["tipo"])


def prepare(question: str, modo: str, opts: dict | None = None, db_path: Path = config.DB_PATH
            ) -> tuple[dict, list[dict], dict]:
    opts = opts or {}
    if modo == "base":
        return {}, [], {"etapa": "recuperacion", "modo": "base", "ejemplos": []}
    if modo not in config.MODOS_CONTEXTO:
        raise ValueError(f"modo_contexto desconocido: {modo!r} (opciones: {', '.join(config.MODOS_CONTEXTO)})")
    excl = _exclusions(opts)

    if modo == "fewshot":
        k = opts.get("k", config.FEWSHOT_K)
        found = fewshot.select_fewshot(question, k=k, modo=opts.get("fewshot_modo", "dinamico"), **excl)
        text, used = fewshot.format_examples(found)
        info = [{"id": e["id"], "pregunta": e["pregunta"], "score": e["score"], "origen": "catalogo"} for e in used]
        etapa = {"etapa": "recuperacion", "modo": f"fewshot-{opts.get('fewshot_modo', 'dinamico')}",
                 "k": k, "ejemplos": info}
        return ({"examples": text} if text else {}), info, etapa

    # rag y harness: umbral + fuentes extra + esquema recortado
    k = opts.get("k", config.RAG_K)
    min_score = opts.get("min_score", config.RAG_MIN_SCORE)
    hits = fewshot.get_retriever("rag").query(question, k=k, min_score=min_score, **excl)
    examples = [{"id": h.id, "pregunta": h.ejemplo["pregunta"], "sql": h.ejemplo["sql"], "score": h.score,
                 "necesidad_base": h.ejemplo.get("necesidad_base"), "tipo": h.ejemplo.get("tipo"),
                 "origen": h.ejemplo.get("origen", "catalogo")} for h in hits]
    if modo == "harness" and len(examples) < k:          # el harness completa con few-shot dinámico
        have = {e["id"] for e in examples}
        for e in fewshot.select_fewshot(question, k=k, modo="dinamico", **excl):
            if e["id"] not in have and len(examples) < k:
                examples.append({**e, "origen": "fewshot"})
    if not examples:
        return {}, [], {"etapa": "recuperacion", "modo": modo, "umbral": min_score, "ejemplos": [],
                        "nota": "ningún ejemplo superó el umbral: no se inyecta nada"}
    text, used = fewshot.format_examples(examples)
    info = [{"id": e["id"], "pregunta": e["pregunta"], "score": e["score"], "origen": _origin(e)} for e in used]
    extra = {"examples": text} if text else {}
    schema, _, _ = se._schema_context_cached(str(Path(db_path).resolve()))
    trimmed = rag.schema_fragment(question, hits, schema)
    if trimmed != schema:
        extra["schema"] = trimmed
    etapa = {"etapa": "recuperacion", "modo": modo, "k": k, "umbral": min_score, "ejemplos": info,
             "esquema_recortado": bool(extra.get("schema")),
             "tokens_esquema": se.estimate_tokens(trimmed)}
    return extra, info, etapa
