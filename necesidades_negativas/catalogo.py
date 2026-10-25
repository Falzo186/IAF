"""Lectura y escritura del catálogo de necesidades negativas (JSONL, UTF-8).

Cada línea es un ejemplo ya resuelto:

    {"id": "N1-neg-003", "necesidad_base": "N1", "tipo": "parafrasis", "pregunta": "...",
     "sql": "...", "resuelto_por": "claude-code", "validado": true,
     "validacion": {...}, "split": "train", "notas": ""}

`split` es determinista (hash del id con semilla fija): ~70 % train y ~30 % heldout. El heldout
solo sirve para evaluar: nada del heldout se inyecta jamás en un prompt (ver fewshot.py y rag.py).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

CATALOGO_PATH = Path(__file__).resolve().parent / "catalogo.jsonl"

TIPOS = ("parafrasis", "filtro_distinto", "agregado_distinto", "casi_igual_trampa", "ruido", "ambigua")
RESUELTO_POR = ("claude-code", "modelo-grande-online", "modelo-grande-manual", "plantilla")

# Semilla del split. Se eligió una vez (la de mejor balance 70/30 por necesidad entre s00..s99, sin mirar resultados) y queda fija:
# cambiarla redistribuye train/heldout y invalida los resultados guardados.
SPLIT_SEED = "iaf-fase11-s86"
HELDOUT_PCT = 30


def normalize_question(text: str) -> str:
    """Minúsculas, sin acentos ni signos, espacios colapsados (para duplicados y exclusiones)."""
    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text)).strip()


def normalize_sql(sql: str) -> str:
    """SQL sin comentarios ni diferencias de espacios/mayúsculas/punto y coma (para comparar texto)."""
    sql = re.sub(r"--[^\n]*", " ", str(sql))
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"\s+", " ", sql).strip().rstrip(";").strip().lower()


def split_for(entry_id: str, seed: str = SPLIT_SEED) -> str:
    h = int(hashlib.sha1(f"{seed}:{entry_id}".encode("utf-8")).hexdigest(), 16) % 100
    return "heldout" if h < HELDOUT_PCT else "train"


def catalog_hash(path: Path | None = None) -> str:
    """Huella del contenido del catálogo (invalida la caché del RAG y queda en los resultados)."""
    try:
        return hashlib.sha256(Path(path or CATALOGO_PATH).read_bytes()).hexdigest()[:16]
    except OSError:
        return "sin-catalogo"


def load_catalog(path: Path | None = None, split: str | None = None,
                 solo_validados: bool = True) -> list[dict]:
    path = Path(path or CATALOGO_PATH)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if solo_validados and not row.get("validado"):
            continue
        if split and row.get("split") != split:
            continue
        rows.append(row)
    return rows


def write_catalog(rows: list[dict], path: Path | None = None) -> None:
    path = Path(path or CATALOGO_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def next_id(rows: list[dict], need: str) -> str:
    used = [int(m.group(1)) for r in rows
            if (m := re.fullmatch(re.escape(need) + r"-neg-(\d+)", r.get("id", "")))]
    return f"{need}-neg-{(max(used) + 1 if used else 1):03d}"


def stats(rows: list[dict]) -> dict:
    """Conteos por necesidad, tipo, split y quién resolvió."""
    out = {"total": len(rows)}
    for key in ("necesidad_base", "tipo", "split", "resuelto_por"):
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.get(key, "?")] = counts.get(r.get(key, "?"), 0) + 1
        out[key] = dict(sorted(counts.items()))
    return out
