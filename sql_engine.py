"""Motor Text-to-SQL: pregunta en español -> SQL -> DataFrame -> respuesta ejecutiva.

Flujo de answer_question:
    enrutador: la pregunta coincide con una necesidad de business_queries
      - y todos sus filtros están soportados -> SQL verificada con parámetros ("verificada")
      - pero pide un filtro no soportado     -> LLM con la SQL verificada como ancla ("llm_anclada")
    si no coincide -> LLM genera SQL ("llm")
    LLM: extraer -> validar -> ejecutar (1 reintento con el error) -> síntesis ejecutiva.

El módulo no tiene estado global mutable: la única memoria es la caché del
contexto de esquema (lru_cache por ruta de BD). Nunca lanza excepciones hacia la UI.
"""

from __future__ import annotations

import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

import pandas as pd
import sqlglot
from sqlglot import exp

import config
import db
from business_queries import (ALL_FILTERS, BUSINESS_QUERIES, BusinessQuery, render_sql,
                              run_business_query)
from db import QueryTimeout

MAX_ROWS = 500
QUERY_TIMEOUT_S = 5.0
HISTORY_TURNS = 2
SYNTH_ROWS = 15
SQL_OPTIONS = {"temperature": 0.0, "num_predict": 400}
SYNTH_OPTIONS = {"temperature": 0.3, "num_predict": 250}

FRIENDLY_ERROR = (
    "No logré construir una consulta válida para esa pregunta. Intenta reformularla con más "
    "detalle, por ejemplo indicando el periodo, la tienda, la categoría o la métrica que te interesa."
)
NO_ROWS_ANSWER = "No se encontraron registros para esa consulta."

LLM = Callable[..., str]


class SQLValidationError(ValueError):
    """La SQL generada no es una consulta de solo lectura válida."""


@dataclass
class QueryResult:
    question: str
    model: str
    sql: str | None = None
    df: pd.DataFrame | None = None
    answer: str = ""
    attempts: int = 0
    error: str | None = None
    timings: dict = field(default_factory=lambda: {"sql_gen": 0.0, "exec": 0.0, "synth": 0.0})
    source: str = "llm"                 # "verificada", "llm_anclada" o "llm"
    business_query_id: str | None = None
    filters: dict = field(default_factory=dict)            # filtros aplicados (verificada)
    unsupported_filters: list = field(default_factory=list)  # motivo del anclaje


# ---------------------------------------------------------------------------
# 3.1 Contexto de esquema compacto
# ---------------------------------------------------------------------------

PROMPT_OBJECTS = ["v_order_lines", "v_orders", "products", "stocks", "stores", "staffs",
                  "customers", "categories", "brands"]

COLUMN_NOTES = {
    "v_order_lines": {
        "status_label": "texto del estado (Completada, Rechazada...)",
        "staff_name": "nombre completo del vendedor",
        "gross_amount": "list_price*quantity (bruto)",
        "discount_amount": "list_price*quantity*discount (descuento cedido)",
        "net_amount": "list_price*quantity*(1-discount) (ingreso neto de la línea)",
    },
    "v_orders": {
        "n_items": "número de líneas de la orden",
        "total_quantity": "unidades de la orden",
        "n_brands": "marcas distintas en la orden",
        "gross_total": "suma de gross_amount",
        "discount_total": "suma de discount_amount",
        "net_total": "suma de net_amount (ingreso neto de la orden)",
        "is_shipped": "1 si shipped_date no es NULL",
        "is_late": "1 si se envió después de required_date",
        "days_late": "días de retraso (0 a tiempo, NULL sin enviar)",
    },
    "stocks": {
        "store_id": "no hay store_name aquí: JOIN stores ON stores.store_id = stocks.store_id",
    },
}

# Tipo de las columnas calculadas de las vistas (PRAGMA table_info las deja vacías).
_COMPUTED_TYPES = {"staff_name": "TEXT", "is_shipped": "INT", "is_late": "INT", "days_late": "INT",
                   "n_items": "INT", "total_quantity": "INT", "n_brands": "INT"}
_TYPE_ABBR = {"INTEGER": "INT", "REAL": "REAL", "TEXT": "TEXT", "": "REAL"}


_ro_connect = db.ro_connect


def _metadata(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key, value FROM db_metadata"))


@lru_cache(maxsize=4)
def _schema_context_cached(db_path: str) -> tuple[str, str, str]:
    conn = _ro_connect(Path(db_path))
    try:
        lines = []
        for obj in PROMPT_OBJECTS:
            cols = []
            for _, name, ctype, *_ in conn.execute(f"PRAGMA table_info({obj})"):
                t = _COMPUTED_TYPES.get(name) or _TYPE_ABBR.get(ctype.upper(), ctype.upper())
                cols.append(f"{name} {t}")
            lines.append(f"{obj}({', '.join(cols)})")
            for col, note in COLUMN_NOTES.get(obj, {}).items():
                lines.append(f"  -- {col}: {note}")

        values = lambda sql: ", ".join(r[0] for r in conn.execute(sql))  # noqa: E731
        meta = _metadata(conn)
        lines += [
            "",
            "Valores válidos:",
            f"- category_name: {values('SELECT category_name FROM categories ORDER BY 1')}",
            f"- brand_name: {values('SELECT brand_name FROM brands ORDER BY 1')}",
            f"- store_name: {values('SELECT store_name FROM stores ORDER BY 1')}",
            "- order_status/status_label: " + ", ".join(
                f"{s}={label}" for s, label in conn.execute(
                    "SELECT order_status, status_label FROM order_status_lookup ORDER BY 1")),
            f"- state (clientes y tiendas): {values('SELECT DISTINCT state FROM customers ORDER BY 1')}",
            f"- reference_date (hoy): {meta['reference_date']}",
            f"- last_completed_date (última venta completada): {meta['last_completed_date']}",
        ]
        return "\n".join(lines), meta["reference_date"], meta["last_completed_date"]
    finally:
        conn.close()


def get_schema_context(db_path: Path = config.DB_PATH) -> str:
    return _schema_context_cached(str(Path(db_path).resolve()))[0]


def estimate_tokens(text: str) -> int:
    """Estimación conservadora (~3.5 caracteres por token en español/SQL)."""
    return int(len(text) / 3.5) + 1


# ---------------------------------------------------------------------------
# 3.2 Prompt de generación de SQL
# ---------------------------------------------------------------------------

FEW_SHOTS: list[tuple[str, str]] = [
    (
        "¿Cuánto ingreso neto generó la categoría Mountain Bikes en 2016?",
        "SELECT ROUND(SUM(net_amount), 2) AS ingreso_neto\n"
        "FROM v_order_lines\n"
        "WHERE order_status = 4 AND category_name = 'Mountain Bikes'\n"
        "  AND strftime('%Y', order_date) = '2016'",
    ),
    (
        "¿Cuáles son las 3 marcas con más ingreso neto?",
        "SELECT brand_name AS marca, ROUND(SUM(net_amount), 2) AS ingreso_neto\n"
        "FROM v_order_lines\n"
        "WHERE order_status = 4\n"
        "GROUP BY brand_name\n"
        "ORDER BY ingreso_neto DESC\n"
        "LIMIT 3",
    ),
    (
        "¿Qué productos no tienen stock en Baldwin Bikes?",
        "SELECT p.product_name AS producto, st.quantity AS stock\n"
        "FROM stocks st\n"
        "JOIN products p ON p.product_id = st.product_id\n"
        "JOIN stores s ON s.store_id = st.store_id\n"
        "WHERE s.store_name = 'Baldwin Bikes' AND st.quantity = 0\n"
        "ORDER BY producto",
    ),
    (
        "¿Qué porcentaje de las órdenes enviadas en 2017 llegó tarde?",
        "SELECT ROUND(100.0 * SUM(is_late) / COUNT(*), 2) AS pct_tarde\n"
        "FROM v_orders\n"
        "WHERE is_shipped = 1 AND strftime('%Y', order_date) = '2017'",
    ),
    (
        "Compara el número de órdenes y el ingreso neto por tienda en 2018.",
        "SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(SUM(net_total), 2) AS ingreso_neto\n"
        "FROM v_orders\n"
        "WHERE order_status = 4 AND strftime('%Y', order_date) = '2018'\n"
        "GROUP BY store_name\n"
        "ORDER BY ingreso_neto DESC",
    ),
    (
        "¿Cuántas unidades de la marca Electra se vendieron por mes en 2016?",
        "SELECT strftime('%Y-%m', order_date) AS mes, SUM(quantity) AS unidades\n"
        "FROM v_order_lines\n"
        "WHERE order_status = 4 AND brand_name = 'Electra'\n"
        "  AND strftime('%Y', order_date) = '2016'\n"
        "GROUP BY mes\n"
        "ORDER BY mes",
    ),
]

SYSTEM_PROMPT_TEMPLATE = """Eres un experto en SQL que responde preguntas de negocio sobre la base Bike Stores.

Esquema:
{schema}

Reglas:
1. Dialecto SQLite. Devuelve UNA sola consulta SELECT dentro de ```sql ... ```, sin explicación.
2. Para dinero usa SIEMPRE net_amount (v_order_lines) o net_total (v_orders), que ya aplican (list_price*quantity)*(1-discount). Nunca recalcules montos.
3. Toda pregunta de ventas, ingresos, ticket o unidades vendidas DEBE filtrar order_status = 4, salvo que se pida otro estado. Rechazadas = order_status = 3.
4. Las fechas son texto ISO. Si la pregunta menciona un año, filtra strftime('%Y', order_date) = 'AAAA'. Para "por mes" agrupa por strftime('%Y-%m', order_date) en una sola columna. "Hoy" = {reference_date}.
5. Compara nombres exactamente con los valores válidos listados.
6. Usa alias legibles en español (AS ingreso_neto) y ROUND(x, 2) para dinero.
7. Rankings: ORDER BY ... DESC LIMIT n (por defecto 10).
8. Usa solo las tablas y columnas del esquema.

Ejemplos:
{examples}"""


def build_system_prompt(db_path: Path = config.DB_PATH) -> str:
    schema, ref_date, _ = _schema_context_cached(str(Path(db_path).resolve()))
    examples = "\n\n".join(f"Pregunta: {q}\n```sql\n{sql}\n```" for q, sql in FEW_SHOTS)
    return SYSTEM_PROMPT_TEMPLATE.format(schema=schema, reference_date=ref_date, examples=examples)


def _history_messages(history: list[dict] | None) -> list[dict]:
    msgs = []
    for turn in (history or [])[-HISTORY_TURNS:]:
        q, sql = turn.get("question"), turn.get("sql")
        if q and sql:
            msgs.append({"role": "user", "content": q})
            msgs.append({"role": "assistant", "content": f"```sql\n{sql}\n```"})
    return msgs


def build_sql_messages(question: str, history: list[dict] | None = None,
                       db_path: Path = config.DB_PATH) -> list[dict]:
    return ([{"role": "system", "content": build_system_prompt(db_path)}]
            + _history_messages(history)
            + [{"role": "user", "content": question}])


# ---------------------------------------------------------------------------
# 3.3 Extracción y validación
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_SQL_RE = re.compile(r"```\s*sql\s*\n?(.*?)(?:```|$)", re.DOTALL | re.IGNORECASE)
_FENCE_ANY_RE = re.compile(r"```[a-zA-Z]*\s*\n?(.*?)(?:```|$)", re.DOTALL)
_START_RE = re.compile(r"\b(SELECT|WITH)\b", re.IGNORECASE)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", sql)


def extract_sql(text: str) -> str:
    """Extrae la consulta SQL de la respuesta del modelo. Devuelve '' si no hay ninguna."""
    text = _THINK_RE.sub("", text or "")
    if "</think>" in text.lower():          # bloque de razonamiento sin apertura
        text = text[text.lower().rfind("</think>") + len("</think>"):]
    elif "<think>" in text.lower():         # razonamiento truncado: no hay SQL después
        text = text[: text.lower().find("<think>")]

    m = _FENCE_SQL_RE.search(text) or _FENCE_ANY_RE.search(text)
    if m:
        sql = m.group(1)
    else:
        start = _START_RE.search(text)
        if not start:
            return ""
        sql = text[start.start():]
        sql = re.split(r";|\n\s*\n", sql, maxsplit=1)[0]  # corta la explicación posterior

    sql = _strip_comments(sql).strip()
    while sql.endswith(";"):
        sql = sql[:-1].rstrip()
    return sql


FORBIDDEN_KEYWORDS = {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "ATTACH",
                      "DETACH", "PRAGMA", "VACUUM", "REPLACE"}
_FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create,
                    exp.Command, exp.Pragma)
_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)


def _check_forbidden_tokens(sql: str) -> None:
    tokens = sqlglot.tokenize(sql, read="sqlite")
    for i, tok in enumerate(tokens):
        if tok.token_type in (sqlglot.TokenType.STRING, sqlglot.TokenType.IDENTIFIER):
            continue  # literales y "identificadores entre comillas" no son palabras clave
        word = tok.text.upper()
        if word in FORBIDDEN_KEYWORDS:
            # replace(x, a, b) es una función de texto inofensiva; REPLACE INTO no lo es.
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if word == "REPLACE" and nxt is not None and nxt.token_type == sqlglot.TokenType.L_PAREN:
                continue
            raise SQLValidationError(f"Operación no permitida: {word}. Solo se admiten consultas SELECT.")


@lru_cache(maxsize=4)
def _db_objects(db_path: str) -> frozenset[str]:
    conn = _ro_connect(Path(db_path))
    try:
        return frozenset(r[0].lower() for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"))
    finally:
        conn.close()


def validate_sql(sql: str, db_path: Path = config.DB_PATH) -> str:
    """Valida que sea una única consulta de lectura sobre objetos existentes.

    Devuelve la SQL lista para ejecutar (con LIMIT 500 si la consulta externa no
    tiene LIMIT) o lanza SQLValidationError.
    """
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise SQLValidationError("La respuesta del modelo no contiene ninguna consulta SQL.")

    _check_forbidden_tokens(sql)
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise SQLValidationError(f"SQL con errores de sintaxis: {str(exc).splitlines()[0]}") from exc
    if len(statements) != 1:
        raise SQLValidationError(f"Se esperaba exactamente 1 sentencia y se recibieron {len(statements)}.")
    stmt = statements[0]
    if not isinstance(stmt, _ALLOWED_ROOTS):
        raise SQLValidationError(f"Solo se permiten consultas SELECT (se recibió {stmt.key.upper()}).")
    bad = next(stmt.find_all(*_FORBIDDEN_NODES), None)
    if bad is not None:
        raise SQLValidationError(f"Operación no permitida dentro de la consulta: {bad.key.upper()}.")

    ctes = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    known = _db_objects(str(Path(db_path).resolve()))
    for table in stmt.find_all(exp.Table):
        if not table.name:
            continue  # p. ej. funciones con valor de tabla sin nombre
        if table.db and table.db.lower() != "main":
            raise SQLValidationError(f"No se permite acceder a otra base de datos: {table.db}.")
        name = table.name.lower()
        if name not in ctes and name not in known:
            raise SQLValidationError(f"La tabla o vista '{table.name}' no existe.")

    if stmt.args.get("limit") is None:
        sql = f"{sql}\nLIMIT {MAX_ROWS}"
    return sql


# ---------------------------------------------------------------------------
# 3.4 Ejecución segura
# ---------------------------------------------------------------------------

def execute_sql(sql: str, db_path: Path = config.DB_PATH,
                timeout: float = QUERY_TIMEOUT_S) -> pd.DataFrame:
    """Ejecuta en una conexión de solo lectura con tiempo máximo."""
    return db.run_query(sql, None, db_path, timeout)


# ---------------------------------------------------------------------------
# 5.2 Enrutador hacia consultas verificadas
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9%+\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _score(norm_question: str, bq: BusinessQuery) -> tuple[int, int, int]:
    """(grupos con coincidencia, raíces coincidentes, caracteres coincidentes)."""
    groups = stems = chars = 0
    for group in bq.keywords:
        hits = [s for s in group if re.search(r"(?<![a-z0-9])" + re.escape(s), norm_question)]
        if hits:
            groups += 1
            stems += len(hits)
            chars += sum(len(h) for h in hits)
    return groups, stems, chars


def match_business_query(question: str) -> BusinessQuery | None:
    """Devuelve la consulta verificada que corresponde a la pregunta, o None.

    Una consulta es candidata si al menos min_score de sus grupos de keywords
    aparecen en la pregunta. Entre candidatas gana la de más grupos; se desempata
    por número de raíces y luego por caracteres coincidentes (coincidencias más
    específicas). Si el empate persiste, no se enruta y responde el LLM. Las
    raíces de `exclude` descartan una consulta.
    """
    norm = normalize_text(question)
    scored = []
    for bq in BUSINESS_QUERIES:
        if any(re.search(r"(?<![a-z0-9])" + re.escape(x), norm) for x in bq.exclude):
            continue
        score = _score(norm, bq)
        if score[0] >= bq.min_score:
            scored.append((score, bq))
    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


# ---------------------------------------------------------------------------
# Extracción de filtros de la pregunta
# ---------------------------------------------------------------------------

MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
          "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
          "diciembre": 12}
STORE_ALIASES = {"Baldwin Bikes": ("baldwin",), "Santa Cruz Bikes": ("santa cruz",),
                 "Rowlett Bikes": ("rowlett",)}
CATEGORY_ALIASES = {
    "Children Bicycles": ("children", "infantil", "infantiles", "para ninos", "de ninos"),
    "Comfort Bicycles": ("comfort", "confort"),
    "Cruisers Bicycles": ("cruiser", "cruisers"),
    "Cyclocross Bicycles": ("cyclocross", "ciclocross"),
    "Electric Bikes": ("electric", "electrica", "electricas", "e-bike", "e-bikes", "ebike", "ebikes"),
    "Mountain Bikes": ("mountain", "de montana"),
    "Road Bikes": ("road bike", "road bikes", "de ruta", "de carretera"),
}
STATE_ALIASES = {"NY": ("nueva york",), "CA": ("california",), "TX": ("texas",)}
# Ciudades que también son palabras comunes o nombres de tienda.
CITY_STOPLIST = {"vista", "corona", "victoria", "encino", "baldwin", "santa cruz", "rowlett",
                 "new york", "shirley", "monroe"}
_PERIOD_RE = re.compile(r"(?:\b(" + "|".join(MONTHS) + r")\s+(?:de(?:l)?\s+)?)?\b(20\d{2})\b")
_TOP_RE = re.compile(
    r"\b(?:top|primer[oa]s|mejores|peores|principales|ultim[oa]s)\s+(\d{1,3})\b"
    r"(?!\s+(?:mes|meses|dias|semanas|anos|trimestres)\b)"
    r"|\b(\d{1,3})\s+(?:productos|ciudades|clientes|vendedores|marcas|categorias|tiendas|articulos|"
    r"bicicletas|modelos)\b")
_COMPARE_RE = re.compile(r"\b(vs|versus|contra|frente a|compar\w*)\b")


def _has(norm: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", norm) is not None


@lru_cache(maxsize=4)
def _entity_names(db_path: str) -> dict:
    """(forma normalizada, valor original) de marcas, ciudades, vendedores y clientes."""
    conn = _ro_connect(Path(db_path))
    try:
        brands = [(normalize_text(b), b) for (b,) in conn.execute("SELECT brand_name FROM brands")]
        cities = [(normalize_text(c), c) for (c,) in conn.execute("SELECT DISTINCT city FROM customers")]
        staff = []
        for first, last in conn.execute("SELECT first_name, last_name FROM staffs"):
            staff += [(normalize_text(f"{first} {last}"), f"{first} {last}"),
                      (normalize_text(first), f"{first} {last}")]
        customers = [(normalize_text(f"{f} {l}"), f"{f} {l}")
                     for f, l in conn.execute("SELECT first_name, last_name FROM customers")]
        return {"marca": brands,
                "ciudad": [c for c in cities if c[0] not in CITY_STOPLIST and len(c[0]) >= 4],
                "vendedor": staff, "cliente": customers}
    finally:
        conn.close()


def extract_filters(question: str, db_path: Path = config.DB_PATH) -> dict:
    """Detecta filtros en la pregunta.

    Devuelve {store_name, date_from, date_to, top_n, unsupported}. Los tres primeros son
    los filtros que las consultas verificadas aceptan como parámetros; `unsupported` es
    una lista de (tipo, valor) con los que no aceptan: categoría, marca, estado, ciudad,
    cliente, vendedor, varias tiendas, comparación de periodos o trimestres. `top_n`
    se compara con el top-N propio de cada consulta en plan_route.
    """
    norm = normalize_text(question)
    out = {"store_name": None, "date_from": None, "date_to": None, "top_n": None, "unsupported": []}
    unsupported = out["unsupported"]

    stores = [name for name, aliases in STORE_ALIASES.items() if any(_has(norm, a) for a in aliases)]
    if len(stores) == 1:
        out["store_name"] = stores[0]
    elif len(stores) > 1:
        unsupported.append(("varias tiendas", ", ".join(stores)))

    periods = []
    for m in _PERIOD_RE.finditer(norm):
        year = int(m.group(2))
        if m.group(1):
            month = MONTHS[m.group(1)]
            last_day = (pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)).day
            periods.append((f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"))
        else:
            periods.append((f"{year}-01-01", f"{year}-12-31"))
    if len(periods) == 1:
        out["date_from"], out["date_to"] = periods[0]
    elif len(periods) == 2 and not _COMPARE_RE.search(norm):
        out["date_from"] = min(p[0] for p in periods)
        out["date_to"] = max(p[1] for p in periods)
    elif periods:
        unsupported.append(("comparación de periodos", ", ".join(p[0][:7] for p in periods)))
    if re.search(r"\b(trimestre|semestre|bimestre)\b", norm):
        unsupported.append(("periodo", "trimestre/semestre"))

    m = _TOP_RE.search(norm)
    if m:
        out["top_n"] = int(m.group(1) or m.group(2))

    for cat, aliases in CATEGORY_ALIASES.items():
        if _has(norm, normalize_text(cat)) or any(_has(norm, a) for a in aliases):
            unsupported.append(("categoria", cat))
    for code, aliases in STATE_ALIASES.items():
        if re.search(rf"\b{code}\b", question) or any(_has(norm, a) for a in aliases):
            unsupported.append(("estado", code))

    names = _entity_names(str(Path(db_path).resolve()))
    for kind in ("marca", "ciudad", "vendedor", "cliente"):
        for value in sorted({value for key, value in names[kind] if _has(norm, key)}):
            unsupported.append((kind, value))
    return out


def plan_route(question: str, db_path: Path = config.DB_PATH) -> tuple:
    """Decide la ruta: ("verificada" | "llm_anclada" | "llm", consulta, filtros, no soportados)."""
    bq = match_business_query(question)
    if bq is None:
        return "llm", None, {}, []
    f = extract_filters(question, db_path)
    unsupported = [u for u in f["unsupported"] if bq.fixed_filters.get(u[0]) != u[1]]
    if f["top_n"] is not None and f["top_n"] != bq.default_top:
        unsupported.append(("top-N", str(f["top_n"])))
    params = {k: f[k] for k in ALL_FILTERS if f[k] is not None and k in bq.supported_filters}
    unsupported += [(k, f[k]) for k in ALL_FILTERS if f[k] is not None and k not in bq.supported_filters]
    return ("llm_anclada" if unsupported else "verificada"), bq, params, unsupported


# ---------------------------------------------------------------------------
# 3.6 Síntesis ejecutiva
# ---------------------------------------------------------------------------

_MONEY_RE = re.compile(r"ingreso|monto|importe|valor|precio|ticket|neto|bruto|cedido|dinero|venta|amount|price|revenue")
_PCT_RE = re.compile(r"pct|porcentaje|percent|tasa")


def format_value(value, column: str = "") -> str:
    col = column.lower()
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "sin dato"
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if _PCT_RE.search(col):
            return f"{value:,.2f}%"
        if _MONEY_RE.search(col):
            return f"${value:,.2f}"
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


def df_to_markdown(df: pd.DataFrame, max_rows: int = SYNTH_ROWS) -> str:
    head = df.head(max_rows)
    cols = [str(c) for c in head.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in head.itertuples(index=False):
        lines.append("| " + " | ".join(format_value(v, c) for v, c in zip(row, cols)) + " |")
    return "\n".join(lines)


def single_value_answer(df: pd.DataFrame) -> str:
    col = str(df.columns[0])
    value = df.iat[0, 0]
    if hasattr(value, "item"):
        value = value.item()
    return f"El resultado ({col.replace('_', ' ')}) es {format_value(value, col)}."


def generic_answer(df: pd.DataFrame) -> str:
    return (f"La consulta devolvió {len(df):,} fila(s). Revisa la tabla de resultados para ver el detalle.")


SYNTH_SYSTEM = (
    "Eres un analista que informa a la dirección de una cadena de tiendas de bicicletas. "
    "Responde en 2 a 4 frases en español, con tono directivo y concreto. Usa SOLO cifras que "
    "aparezcan en el resultado; no inventes ni calcules cifras nuevas. Escribe el dinero como "
    "$1,234.56. No menciones SQL, tablas, columnas ni consultas."
)


def build_synthesis_messages(question: str, sql: str, df: pd.DataFrame,
                             key_fact: str | None = None) -> list[dict]:
    shown = min(len(df), SYNTH_ROWS)
    fact = f"Hallazgo principal (ya calculado, úsalo como base): {key_fact}\n\n" if key_fact else ""
    user = (
        f"Pregunta: {question}\n\n{fact}"
        f"Consulta ejecutada:\n{sql}\n\n"
        f"Resultado ({len(df)} filas en total; se muestran {shown}):\n{df_to_markdown(df)}"
    )
    return [{"role": "system", "content": SYNTH_SYSTEM}, {"role": "user", "content": user}]


def template_answer(df: pd.DataFrame, business_query_id: str | None) -> str:
    """Respuesta sin LLM: frase determinística de la necesidad, o una genérica."""
    if business_query_id:
        try:
            import analytics
            return analytics.insight(business_query_id, df)
        except Exception:
            pass
    return generic_answer(df)


def synthesize(question: str, sql: str, df: pd.DataFrame, model: str, llm: LLM,
               business_query_id: str | None = None) -> tuple[str, bool]:
    """Devuelve (respuesta, se_llamo_al_llm). Si el LLM falla usa una plantilla."""
    if df.empty:
        return NO_ROWS_ANSWER, False
    if df.shape == (1, 1):
        return single_value_answer(df), False
    try:
        key_fact = template_answer(df, business_query_id) if business_query_id else None
        text = llm(model, build_synthesis_messages(question, sql, df, key_fact), **SYNTH_OPTIONS)
        text = _THINK_RE.sub("", text or "").strip()
        if "</think>" in text.lower():
            text = text[text.lower().rfind("</think>") + len("</think>"):].strip()
        return (text or template_answer(df, business_query_id)), True
    except Exception:
        return template_answer(df, business_query_id), True


# ---------------------------------------------------------------------------
# 3.5 Bucle principal
# ---------------------------------------------------------------------------

def _default_llm() -> LLM:
    import ollama_manager
    return ollama_manager.chat


def _run_sql(sql: str, db_path: Path) -> tuple[str, pd.DataFrame, float]:
    final_sql = validate_sql(sql, db_path)
    t0 = time.perf_counter()
    df = execute_sql(final_sql, db_path)
    return final_sql, df, time.perf_counter() - t0


def answer_question(question: str, model: str, history: list[dict] | None = None,
                    llm: LLM | None = None, *, db_path: Path = config.DB_PATH,
                    use_router: bool = True, synthesize_answer: bool = True,
                    verified_synthesis: bool | None = None) -> QueryResult:
    """Responde una pregunta en español. Nunca lanza excepciones: los errores van en QueryResult.error.

    verified_synthesis: si la ruta es "verificada", ¿redacta la respuesta el LLM? Con False
    (por defecto, config.VERIFIED_SYNTHESIS) se usa la frase determinística de analytics.insight.
    """
    if verified_synthesis is None:
        verified_synthesis = config.VERIFIED_SYNTHESIS
    result = QueryResult(question=question, model=model)
    try:
        llm = llm or _default_llm()
        db_path = Path(db_path)

        route, bq, params, unsupported = (plan_route(question, db_path) if use_router
                                          else ("llm", None, {}, []))
        if route == "verificada":
            result.source, result.business_query_id, result.filters = "verificada", bq.id, params
            result.sql = render_sql(bq, **params)
            t0 = time.perf_counter()
            result.df = run_business_query(bq, **params, limit=MAX_ROWS, db_path=db_path)
            result.timings["exec"] = time.perf_counter() - t0
        else:
            anchor = None
            if route == "llm_anclada":
                result.source, result.business_query_id = "llm_anclada", bq.id
                result.unsupported_filters = unsupported
                anchor = (bq, render_sql(bq, **params))
            _generate_and_run(result, question, history, llm, db_path, anchor)
            if result.error:
                return result

        if synthesize_answer:
            t0 = time.perf_counter()
            if route == "verificada" and not verified_synthesis:
                result.answer = (NO_ROWS_ANSWER if result.df.empty
                                 else template_answer(result.df, result.business_query_id))
            else:
                result.answer, _ = synthesize(question, result.sql, result.df, model, llm,
                                              result.business_query_id if route == "verificada" else None)
            result.timings["synth"] = time.perf_counter() - t0
    except Exception as exc:  # red de seguridad: nada escapa hacia la UI
        result.error = f"{type(exc).__name__}: {exc}"
        result.answer = FRIENDLY_ERROR
        result.df = None
    return result


ANCHOR_TEMPLATE = (
    "\n\nConsulta de referencia para esta necesidad ({titulo}). Está verificada: conserva su "
    "forma de calcular los montos y adáptala a la pregunta (agrega o cambia filtros como "
    "categoría, marca, ciudad, cliente, vendedor o el top-N que se pide):\n```sql\n{sql}\n```"
)


def _generate_and_run(result: QueryResult, question: str, history: list[dict] | None,
                      llm: LLM, db_path: Path, anchor: tuple | None = None) -> None:
    messages = build_sql_messages(question, history, db_path)
    if anchor is not None:
        bq, ref_sql = anchor
        messages[0] = {"role": "system", "content": messages[0]["content"]
                       + ANCHOR_TEMPLATE.format(titulo=bq.titulo, sql=ref_sql)}
    last_error = None
    for attempt in (1, 2):
        result.attempts = attempt
        t0 = time.perf_counter()
        try:
            raw = llm(result.model, messages, **SQL_OPTIONS)
        except Exception as exc:
            result.timings["sql_gen"] += time.perf_counter() - t0
            result.error = str(exc)
            result.answer = ("No pude comunicarme con el modelo de lenguaje local. Verifica que Ollama "
                             "esté en ejecución y que el modelo esté descargado.")
            return
        result.timings["sql_gen"] += time.perf_counter() - t0

        sql = extract_sql(raw)
        result.sql = sql or None
        try:
            result.sql, result.df, exec_t = _run_sql(sql, db_path)
            result.timings["exec"] += exec_t
            result.error = None
            return
        except (SQLValidationError, QueryTimeout, sqlite3.Error, pd.errors.DatabaseError) as exc:
            last_error = str(exc)
            messages = messages + [
                {"role": "assistant", "content": f"```sql\n{sql}\n```" if sql else (raw or "")},
                {"role": "user", "content": (
                    f"Esa consulta falló con este error: {last_error}\n"
                    "Corrígela usando solo el esquema dado. Devuelve solo la consulta SQL corregida "
                    "dentro de ```sql ... ```.")},
            ]
    result.error = last_error
    result.answer = FRIENDLY_ERROR
    result.df = None
