"""RAG ligero y léxico (fase 11): recupera ejemplos resueltos y fragmentos de esquema. Sin red.

Sin modelos de embeddings: TF-IDF en Python puro sobre n-gramas de palabra (1-2) y de caracteres
(3-5, para tolerar faltas de ortografía), similitud del coseno, normalización (minúsculas, sin
acentos, sin stopwords en español). RAM despreciable (cientos de documentos).

Qué indexa: ejemplos validados del split `train` del catálogo (nunca `heldout`), las 10 necesidades
verificadas (pregunta de reference_answers.yaml + su SQL) y los patrones aprobados a mano
(fewshot_candidates.json). Un resultado por debajo de `config.RAG_MIN_SCORE` no se inyecta.

Diferencia con fewshot.py: el few-shot dinámico entrega siempre los k más parecidos del catálogo;
el RAG aplica un umbral, indexa más fuentes, recorta el esquema a lo relevante y deja una traza
(qué se recuperó, con qué puntaje) para mostrarla al usuario.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

import config
from necesidades_negativas import catalogo

STOPWORDS = frozenset("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun aunque cada como con contra cual
cuales cuando cuanta cuantas cuanto cuantos de del desde donde dos el ella ellas ello ellos en entre era
es esa esas ese eso esos esta estan estas este esto estos fue ha hay la las le les lo los mas me mi mis mucho
muy nos nosotros o os otra otras otro otros para pero poco por porque que quien quienes se sea ser si sin
sobre son su sus tambien te tiene tienen todo todos tu tus un una unas uno unos y ya yo dame dime muestra
muestrame dar dime hay estamos tenemos
""".split())

WORD_WEIGHT, CHAR_WEIGHT = 1.0, 0.6
CACHE_VERSION = 2


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text)).strip()


def _stem(word: str) -> str:
    """Quita plurales y terminaciones comunes: ventas/venta, ordenes/orden, clientes/cliente."""
    for suffix in ("es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    return [_stem(w) for w in normalize(text).split() if w not in STOPWORDS and len(w) > 1]


def features(text: str) -> dict[str, float]:
    """Vector disperso (sin normalizar) de n-gramas de palabra y de caracteres."""
    words = tokens(text)
    feats: dict[str, float] = {}
    for n in (1, 2):
        for i in range(len(words) - n + 1):
            key = "w:" + " ".join(words[i:i + n])
            feats[key] = feats.get(key, 0.0) + WORD_WEIGHT
    for w in words:
        padded = f"^{w}$"
        for n in (3, 4, 5):
            for i in range(len(padded) - n + 1):
                key = "c:" + padded[i:i + n]
                feats[key] = feats.get(key, 0.0) + CHAR_WEIGHT
    return feats


@dataclass
class Hit:
    score: float
    ejemplo: dict

    @property
    def id(self) -> str:
        return self.ejemplo["id"]


@dataclass
class Retriever:
    docs: list[dict] = field(default_factory=list)
    idf: dict[str, float] = field(default_factory=dict)
    vectors: list[dict[str, float]] = field(default_factory=list)
    signature: str = ""

    # --- construcción ---------------------------------------------------------------
    @staticmethod
    def collect_docs(include_verified: bool = True, include_patterns: bool = True,
                     catalog_path: Path | None = None) -> list[dict]:
        docs = [dict(r, origen="catalogo") for r in catalogo.load_catalog(catalog_path, split="train")]
        if include_verified:
            docs += _verified_docs()
        if include_patterns:
            docs += _pattern_docs()
        return docs

    @classmethod
    def build(cls, include_verified: bool = True, include_patterns: bool = True,
              catalog_path: Path | None = None, use_cache: bool = True,
              cache_path: Path | None = None) -> "Retriever":
        docs = cls.collect_docs(include_verified, include_patterns, catalog_path)
        sig = _signature(docs, catalog_path)
        cache_path = Path(cache_path or config.CACHE_DIR / "rag_index.json")
        if use_cache:
            cached = cls._load(cache_path, sig)
            if cached is not None:
                return cached
        inst = cls._index(docs, sig)
        if use_cache:
            inst._save(cache_path)
        return inst

    @classmethod
    def _index(cls, docs: list[dict], sig: str) -> "Retriever":
        raw = [features(d["pregunta"]) for d in docs]
        df: dict[str, int] = {}
        for feats in raw:
            for key in feats:
                df[key] = df.get(key, 0) + 1
        n = max(1, len(docs))
        idf = {k: math.log((1 + n) / (1 + c)) + 1.0 for k, c in df.items()}
        return cls(docs, idf, [_vectorize(f, idf) for f in raw], sig)

    @classmethod
    def _load(cls, path: Path, sig: str) -> "Retriever | None":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if data.get("version") != CACHE_VERSION or data.get("signature") != sig:
            return None     # el catálogo (o el código del índice) cambió: se reconstruye
        return cls(data["docs"], data["idf"], data["vectors"], sig)

    def _save(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"version": CACHE_VERSION, "signature": self.signature,
                                        "docs": self.docs, "idf": self.idf, "vectors": self.vectors},
                                       ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass   # la caché es opcional

    # --- consulta -------------------------------------------------------------------
    def query(self, pregunta: str, k: int = 3, exclude_ids=(), min_score: float | None = None,
              exclude_questions=(), exclude_sql=(), exclude_need: str | None = None) -> list[Hit]:
        """Los k documentos más parecidos con puntaje >= min_score (None = sin umbral).

        Exclusiones (todas opcionales, las usa la evaluación para no dar pistas de la respuesta):
        por id, por pregunta normalizada, por SQL idéntica (normalizada) y por necesidad completa.
        """
        qvec = _vectorize(features(pregunta), self.idf)
        skip_ids, skip_q = set(exclude_ids), {catalogo.normalize_question(q) for q in exclude_questions}
        skip_sql = {catalogo.normalize_sql(s) for s in exclude_sql}
        hits = []
        for doc, vec in zip(self.docs, self.vectors):
            if doc["id"] in skip_ids or catalogo.normalize_question(doc["pregunta"]) in skip_q:
                continue
            if exclude_need and doc.get("necesidad_base") == exclude_need:
                continue
            if skip_sql and catalogo.normalize_sql(doc["sql"]) in skip_sql:
                continue
            score = sum(w * vec.get(key, 0.0) for key, w in qvec.items())
            if score > 0 and (min_score is None or score >= min_score):
                hits.append(Hit(round(score, 4), doc))
        hits.sort(key=lambda h: (-h.score, h.id))
        return hits[:k]


def _vectorize(feats: dict[str, float], idf: dict[str, float]) -> dict[str, float]:
    vec = {k: (1 + math.log(v)) * idf[k] for k, v in feats.items() if k in idf}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: round(v / norm, 6) for k, v in vec.items()}


def _signature(docs: list[dict], catalog_path: Path | None) -> str:
    body = json.dumps([(d["id"], d["pregunta"], d["sql"]) for d in docs], ensure_ascii=False)
    return f"{catalogo.catalog_hash(catalog_path)}-{sha256(body.encode('utf-8')).hexdigest()[:12]}"


def _verified_docs() -> list[dict]:
    """Las 10 necesidades verificadas como documentos (pregunta del YAML + SQL verificada)."""
    from business_queries import BUSINESS_QUERIES, render_sql
    try:
        import yaml
        answers = yaml.safe_load((config.BASE_DIR / "reference_answers.yaml").read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - sin el YAML se usan los títulos
        answers = {}
    docs = []
    for bq in BUSINESS_QUERIES:
        question = (answers.get(bq.id) or {}).get("pregunta") or bq.titulo
        docs.append({"id": bq.id, "necesidad_base": bq.id, "tipo": "verificada", "pregunta": question,
                     "sql": render_sql(bq).strip(), "origen": "verificada", "split": "train"})
    return docs


def _pattern_docs() -> list[dict]:
    """Patrones aprobados a mano con review_patterns.py (fewshot_candidates.json)."""
    try:
        rows = json.loads(Path(config.FEWSHOT_CANDIDATES_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [{"id": f"patron-{i + 1:03d}", "necesidad_base": None, "tipo": "patron",
             "pregunta": r["pregunta"], "sql": r["sql"], "origen": "patron", "split": "train"}
            for i, r in enumerate(rows) if r.get("pregunta") and r.get("sql")]


# ---------------------------------------------------------------------------
# Fragmentos de esquema relevantes
# ---------------------------------------------------------------------------

_BLOCK_START = re.compile(r"^(\w+)\(")
# Vecinos de llave foránea de las tablas base (un salto): para no quitar el JOIN que hace falta.
NEIGHBORS = {
    "stocks": ("products", "stores"), "products": ("brands", "categories"),
    "customers": (), "staffs": ("stores",), "stores": (), "categories": (), "brands": (),
}
DEFAULT_OBJECTS = ("v_order_lines", "v_orders")


def split_schema(schema: str) -> tuple[dict[str, str], str]:
    """(bloques por objeto, resto). El resto es la sección "Valores válidos"."""
    head, _, tail = schema.partition("\n\nValores válidos:")
    blocks: dict[str, list[str]] = {}
    current = None
    for line in head.splitlines():
        m = _BLOCK_START.match(line)
        if m:
            current = m.group(1)
            blocks[current] = [line]
        elif current:
            blocks[current].append(line)
    return {k: "\n".join(v) for k, v in blocks.items()}, ("\n\nValores válidos:" + tail if tail else "")


def relevant_objects(pregunta: str, hits: list[Hit], schema_blocks: dict[str, str]) -> list[str]:
    """Objetos del esquema que conviene mostrar: los de las SQL recuperadas, los que la pregunta
    nombra (tabla o columna) y siempre las dos vistas de ventas."""
    import sqlglot
    from sqlglot import exp
    chosen = set(DEFAULT_OBJECTS)
    for h in hits:
        try:
            for t in sqlglot.parse_one(h.ejemplo["sql"], read="sqlite").find_all(exp.Table):
                if t.name in schema_blocks:
                    chosen.add(t.name)
        except sqlglot.errors.SqlglotError:
            continue
    words = set(tokens(pregunta))
    for name, block in schema_blocks.items():
        cols = {_stem(p) for c in re.findall(r"[a-z_]+", block.lower().split("--")[0]) for p in c.split("_")}
        parts = {_stem(p) for p in name.split("_")}
        if words & parts or (words & cols - {"id", "name", "date", "amount", "total", "order"}):
            chosen.add(name)
    for name in list(chosen):
        chosen.update(n for n in NEIGHBORS.get(name, ()) if n in schema_blocks)
    return [n for n in schema_blocks if n in chosen]


def schema_fragment(pregunta: str, hits: list[Hit], schema: str) -> str:
    """El esquema de producción recortado a los objetos relevantes (más los valores válidos).

    Si el recorte no quita nada, devuelve el esquema original sin cambios.
    """
    blocks, rest = split_schema(schema)
    if not blocks:
        return schema
    keep = relevant_objects(pregunta, hits, blocks)
    if len(keep) >= len(blocks):
        return schema
    return "\n".join(blocks[n] for n in keep) + rest
