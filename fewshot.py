"""Few-shot (fase 11): montar ejemplos ya resueltos en el prompt para que el modelo local reconozca
"esta pregunta se parece a una que ya me hicieron".

Dos variantes medibles:
  estatico   los mismos k ejemplos del catálogo para toda pregunta (orden fijo y determinista)
  dinamico   los k ejemplos del catálogo más parecidos a la pregunta (recuperación léxica, rag.py)

Reglas de no-fuga: solo se usa el split `train`; el `heldout` no se puede pedir ni por error
(`split="heldout"` lanza ValueError). La evaluación excluye por id, por pregunta, por SQL idéntica a
la referencia o por necesidad completa (ver `rag.Retriever.query`). Los ejemplos se añaden DESPUÉS de
los de producción (sql_engine.FEW_SHOTS) y con un tope de caracteres (config.FEWSHOT_MAX_CHARS).
"""

from __future__ import annotations

import config
import rag
from necesidades_negativas import catalogo

HEADER = ("Ejemplos de preguntas parecidas ya resueltas (sigue el estilo; NO los copies si la pregunta "
          "pide otra métrica, otro filtro o otra tabla):")
STATIC_NEED_ORDER = ("N8", "N3", "N10", "N5", "N1", "N2", "N4", "N6", "N7", "N9")   # las SQL más cortas primero

_RETRIEVERS: dict = {}


def reset_cache() -> None:
    _RETRIEVERS.clear()


def get_retriever(kind: str = "fewshot") -> rag.Retriever:
    """Retriever en memoria por tipo ("fewshot": solo catálogo; "rag": catálogo + verificadas + patrones)."""
    key = (kind, catalogo.catalog_hash(), _mtime(config.FEWSHOT_CANDIDATES_PATH), str(config.CACHE_DIR))
    if key not in _RETRIEVERS:
        full = kind == "rag"
        _RETRIEVERS.clear()
        _RETRIEVERS[key] = rag.Retriever.build(
            include_verified=full, include_patterns=full,
            cache_path=config.CACHE_DIR / f"{kind}_index.json")
    return _RETRIEVERS[key]


def _mtime(path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _excluded(row: dict, exclude_ids, exclude_questions, exclude_sql, exclude_need) -> bool:
    return (row["id"] in set(exclude_ids)
            or catalogo.normalize_question(row["pregunta"]) in {catalogo.normalize_question(q) for q in exclude_questions}
            or (exclude_need is not None and row.get("necesidad_base") == exclude_need)
            or catalogo.normalize_sql(row["sql"]) in {catalogo.normalize_sql(s) for s in exclude_sql})


def static_pool() -> list[dict]:
    """Candidatos fijos, en orden determinista: una necesidad tras otra, paráfrasis primero."""
    rows = catalogo.load_catalog(split="train")
    def key(r):
        need = STATIC_NEED_ORDER.index(r["necesidad_base"]) if r["necesidad_base"] in STATIC_NEED_ORDER else 99
        return (r["tipo"] != "parafrasis", need, r["id"])
    return sorted(rows, key=key)


def select_fewshot(pregunta: str, k: int | None = None, exclude_ids=(), split: str = "train",
                   modo: str = "dinamico", exclude_questions=(), exclude_sql=(),
                   exclude_need: str | None = None) -> list[dict]:
    """Ejemplos {id, pregunta, sql, score, necesidad_base, tipo}. Nunca del split heldout."""
    if split != "train":
        raise ValueError("Solo se pueden inyectar ejemplos del split 'train' (el heldout es para evaluar).")
    k = config.FEWSHOT_K if k is None else k
    if modo == "estatico":
        out, seen_needs = [], set()
        for row in static_pool():
            if _excluded(row, exclude_ids, exclude_questions, exclude_sql, exclude_need):
                continue
            if row["necesidad_base"] in seen_needs:      # diversidad: una por necesidad
                continue
            seen_needs.add(row["necesidad_base"])
            out.append(_brief(row, None))
            if len(out) >= k:
                break
        return out
    if modo != "dinamico":
        raise ValueError(f"modo de few-shot desconocido: {modo!r}")
    hits = get_retriever("fewshot").query(pregunta, k=k, exclude_ids=exclude_ids,
                                          exclude_questions=exclude_questions,
                                          exclude_sql=exclude_sql, exclude_need=exclude_need)
    return [_brief(h.ejemplo, h.score) for h in hits]


def _brief(row: dict, score: float | None) -> dict:
    return {"id": row["id"], "pregunta": row["pregunta"], "sql": row["sql"], "score": score,
            "necesidad_base": row.get("necesidad_base"), "tipo": row.get("tipo")}


def format_examples(examples: list[dict], max_chars: int | None = None) -> tuple[str, list[dict]]:
    """Texto para el bloque de ejemplos del prompt y los ejemplos que sí cupieron en el presupuesto."""
    budget = config.FEWSHOT_MAX_CHARS if max_chars is None else max_chars
    blocks, used, total = [], [], 0
    for ex in examples:
        block = f"Pregunta: {ex['pregunta']}\n```sql\n{ex['sql'].strip()}\n```"
        if total + len(block) + 2 > budget:
            continue                                  # no cabe: se prueba con el siguiente (más corto)
        blocks.append(block)
        used.append(ex)
        total += len(block) + 2
    if not blocks:
        return "", []
    return HEADER + "\n\n" + "\n\n".join(blocks), used
