"""Bitácora de patrones candidatos (fase 7). SOLO para revisión humana.

Cuando el chat resuelve una pregunta por la ruta "llm" o "llm_anclada" y la SQL se ejecuta sin
error, se anota una línea en learned_patterns.jsonl (append-only). Que se ejecute NO significa
que sea correcta: el modelo pudo devolver un resultado equivocado. Nada en la aplicación lee
este archivo: no cambia el prompt, no alimenta al modelo ni "aprende" solo. Lo consume
review_patterns.py, donde una persona decide qué ejemplos valen la pena.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import config

LOGGED_SOURCES = ("llm", "llm_anclada")


@lru_cache(maxsize=4)
def _hash_cached(path: str, mtime_ns: int, size: int) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def db_hash(db_path: Path | None = None) -> str:
    """Huella del contenido de la BD (para saber con qué datos se generó cada patrón)."""
    path = Path(db_path or config.DB_PATH)
    try:
        st = path.stat()
        return _hash_cached(str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return "desconocido"


def log_pattern(result, path: Path | None = None, db_path: Path | None = None) -> bool:
    """Anota el resultado si cumple la condición. Devuelve True si escribió. Nunca lanza."""
    try:
        if result.source not in LOGGED_SOURCES or result.error is not None:
            return False
        if not result.sql or result.df is None:
            return False
        entry = {
            "pregunta": result.question,
            "sql": result.sql,
            "modelo": result.model,
            "fuente": result.source,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "db_hash": db_hash(db_path),
        }
        path = Path(path or config.LEARNED_PATTERNS_PATH)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception:  # la bitácora jamás debe romper el chat
        return False


def read_patterns(path: Path | None = None) -> list[dict]:
    path = Path(path or config.LEARNED_PATTERNS_PATH)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # una línea dañada no invalida el resto
    return out
