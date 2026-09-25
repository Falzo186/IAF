"""Construye la base SQLite de Bike Stores a partir de los CSV.

Uso:
    python database_builder.py            # construye solo si falta la BD o algún CSV es más nuevo
    python database_builder.py --force    # reconstruye siempre
    python database_builder.py --check    # solo valida la BD existente e imprime un reporte

La construcción es atómica: se escribe en ``bikestores.db.tmp``, se valida y
solo entonces reemplaza a ``bikestores.db``. Si algo falla, la BD anterior se
conserva intacta.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config

log = logging.getLogger("database_builder")

# Tokens que se interpretan como NULL real.
NULL_TOKENS = {"", "NULL", "null", "NaN", "nan"}

# Formatos de fecha que se intentan detectar, en orden de preferencia.
DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%m-%d-%Y",
]

# Tipos lógicos: int, real, text, date.
# El orden de TABLES es el orden de dependencias (padres antes que hijos).
TABLES: dict[str, dict[str, str]] = {
    "categories": {"category_id": "int", "category_name": "text"},
    "brands": {"brand_id": "int", "brand_name": "text"},
    "products": {
        "product_id": "int", "product_name": "text", "brand_id": "int",
        "category_id": "int", "model_year": "int", "list_price": "real",
    },
    "customers": {
        "customer_id": "int", "first_name": "text", "last_name": "text",
        "phone": "text", "email": "text", "street": "text", "city": "text",
        "state": "text", "zip_code": "text",
    },
    "stores": {
        "store_id": "int", "store_name": "text", "phone": "text", "email": "text",
        "street": "text", "city": "text", "state": "text", "zip_code": "text",
    },
    "staffs": {
        "staff_id": "int", "first_name": "text", "last_name": "text",
        "email": "text", "phone": "text", "active": "int", "store_id": "int",
        "manager_id": "int",
    },
    "orders": {
        "order_id": "int", "customer_id": "int", "order_status": "int",
        "order_date": "date", "required_date": "date", "shipped_date": "date",
        "store_id": "int", "staff_id": "int",
    },
    "order_items": {
        "order_id": "int", "item_id": "int", "product_id": "int",
        "quantity": "int", "list_price": "real", "discount": "real",
    },
    "stocks": {"store_id": "int", "product_id": "int", "quantity": "int"},
}

SCHEMA_SQL = """
CREATE TABLE categories (
    category_id   INTEGER PRIMARY KEY,
    category_name TEXT NOT NULL
);

CREATE TABLE brands (
    brand_id   INTEGER PRIMARY KEY,
    brand_name TEXT NOT NULL
);

CREATE TABLE products (
    product_id   INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    brand_id     INTEGER NOT NULL REFERENCES brands(brand_id),
    category_id  INTEGER NOT NULL REFERENCES categories(category_id),
    model_year   INTEGER,
    list_price   REAL
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    first_name  TEXT,
    last_name   TEXT,
    phone       TEXT,
    email       TEXT,
    street      TEXT,
    city        TEXT,
    state       TEXT,
    zip_code    TEXT
);

CREATE TABLE stores (
    store_id   INTEGER PRIMARY KEY,
    store_name TEXT NOT NULL,
    phone      TEXT,
    email      TEXT,
    street     TEXT,
    city       TEXT,
    state      TEXT,
    zip_code   TEXT
);

CREATE TABLE staffs (
    staff_id   INTEGER PRIMARY KEY,
    first_name TEXT,
    last_name  TEXT,
    email      TEXT,
    phone      TEXT,
    active     INTEGER,
    store_id   INTEGER NOT NULL REFERENCES stores(store_id),
    manager_id INTEGER NULL REFERENCES staffs(staff_id)
);

CREATE TABLE orders (
    order_id      INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers(customer_id),
    order_status  INTEGER NOT NULL CHECK (order_status IN (1, 2, 3, 4)),
    order_date    TEXT NOT NULL,
    required_date TEXT,
    shipped_date  TEXT NULL,
    store_id      INTEGER NOT NULL REFERENCES stores(store_id),
    staff_id      INTEGER NOT NULL REFERENCES staffs(staff_id)
);

CREATE TABLE order_items (
    order_id   INTEGER NOT NULL REFERENCES orders(order_id),
    item_id    INTEGER NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity   INTEGER NOT NULL,
    list_price REAL NOT NULL,
    discount   REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (order_id, item_id)
);

CREATE TABLE stocks (
    store_id   INTEGER NOT NULL REFERENCES stores(store_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity   INTEGER,
    PRIMARY KEY (store_id, product_id)
);

CREATE TABLE order_status_lookup (
    order_status INTEGER PRIMARY KEY,
    status_label TEXT NOT NULL
);

CREATE TABLE db_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Índices sobre llaves foráneas
CREATE INDEX idx_products_brand_id       ON products(brand_id);
CREATE INDEX idx_products_category_id    ON products(category_id);
CREATE INDEX idx_staffs_store_id         ON staffs(store_id);
CREATE INDEX idx_staffs_manager_id       ON staffs(manager_id);
CREATE INDEX idx_orders_customer_id      ON orders(customer_id);
CREATE INDEX idx_orders_store_id         ON orders(store_id);
CREATE INDEX idx_orders_staff_id         ON orders(staff_id);
CREATE INDEX idx_order_items_order_id    ON order_items(order_id);
CREATE INDEX idx_order_items_product_id  ON order_items(product_id);
CREATE INDEX idx_stocks_store_id         ON stocks(store_id);
CREATE INDEX idx_stocks_product_id       ON stocks(product_id);

-- Índices para los patrones de consulta analíticos
CREATE INDEX idx_orders_order_date       ON orders(order_date);
CREATE INDEX idx_orders_order_status     ON orders(order_status);
CREATE INDEX idx_orders_store_date       ON orders(store_id, order_date);
CREATE INDEX idx_customers_city          ON customers(city);
CREATE INDEX idx_stocks_quantity         ON stocks(quantity);

-- v_order_lines: una fila por línea de pedido (order_items) enriquecida con la
-- orden, su estado legible, la tienda, el vendedor, el cliente y el producto
-- (marca y categoría). Es la fuente única de verdad para montos:
--   gross_amount    = list_price * quantity
--   discount_amount = list_price * quantity * discount
--   net_amount      = list_price * quantity * (1 - discount)
-- discount es un decimal entre 0 y 1. Se usan LEFT JOIN en las dimensiones
-- para que ninguna línea desaparezca aunque falte un dato de catálogo.
CREATE VIEW v_order_lines AS
SELECT
    oi.order_id,
    oi.item_id,
    o.order_date,
    o.order_status,
    sl.status_label,
    o.store_id,
    s.store_name,
    o.staff_id,
    st.first_name || ' ' || st.last_name        AS staff_name,
    o.customer_id,
    c.city                                      AS customer_city,
    c.state                                     AS customer_state,
    oi.product_id,
    p.product_name,
    b.brand_name,
    cat.category_name,
    oi.quantity,
    oi.list_price,
    oi.discount,
    oi.list_price * oi.quantity                     AS gross_amount,
    oi.list_price * oi.quantity * oi.discount       AS discount_amount,
    oi.list_price * oi.quantity * (1 - oi.discount) AS net_amount
FROM order_items oi
JOIN orders o                     ON o.order_id = oi.order_id
LEFT JOIN order_status_lookup sl  ON sl.order_status = o.order_status
LEFT JOIN stores s                ON s.store_id = o.store_id
LEFT JOIN staffs st               ON st.staff_id = o.staff_id
LEFT JOIN customers c             ON c.customer_id = o.customer_id
LEFT JOIN products p              ON p.product_id = oi.product_id
LEFT JOIN brands b                ON b.brand_id = p.brand_id
LEFT JOIN categories cat          ON cat.category_id = p.category_id;

-- v_orders: una fila por orden. Agrega v_order_lines (misma fórmula de montos)
-- y añade indicadores logísticos:
--   n_items     = número de líneas de la orden; total_quantity = unidades
--   n_brands    = marcas distintas en la orden
--   gross_total / discount_total / net_total = sumas de las líneas (0 si no hay)
--   is_shipped  = 1 si shipped_date no es NULL
--   is_late     = 1 si se envió y shipped_date > required_date (0 en otro caso)
--   days_late   = días de retraso (0 si llegó a tiempo, NULL si no se ha enviado)
CREATE VIEW v_orders AS
SELECT
    o.order_id,
    o.order_date,
    o.required_date,
    o.shipped_date,
    o.order_status,
    sl.status_label,
    o.store_id,
    s.store_name,
    o.staff_id,
    st.first_name || ' ' || st.last_name AS staff_name,
    o.customer_id,
    c.city                               AS customer_city,
    c.state                              AS customer_state,
    COALESCE(agg.n_items, 0)             AS n_items,
    COALESCE(agg.total_quantity, 0)      AS total_quantity,
    COALESCE(agg.n_brands, 0)            AS n_brands,
    COALESCE(agg.gross_total, 0)         AS gross_total,
    COALESCE(agg.discount_total, 0)      AS discount_total,
    COALESCE(agg.net_total, 0)           AS net_total,
    CASE WHEN o.shipped_date IS NOT NULL THEN 1 ELSE 0 END AS is_shipped,
    CASE WHEN o.shipped_date IS NOT NULL AND o.shipped_date > o.required_date
         THEN 1 ELSE 0 END                                  AS is_late,
    CASE WHEN o.shipped_date IS NULL THEN NULL
         ELSE MAX(0, CAST(julianday(o.shipped_date) - julianday(o.required_date) AS INTEGER))
    END                                                     AS days_late
FROM orders o
LEFT JOIN (
    SELECT
        order_id,
        COUNT(*)                   AS n_items,
        SUM(quantity)              AS total_quantity,
        COUNT(DISTINCT brand_name) AS n_brands,
        SUM(gross_amount)          AS gross_total,
        SUM(discount_amount)       AS discount_total,
        SUM(net_amount)            AS net_total
    FROM v_order_lines
    GROUP BY order_id
) agg                             ON agg.order_id = o.order_id
LEFT JOIN order_status_lookup sl  ON sl.order_status = o.order_status
LEFT JOIN stores s                ON s.store_id = o.store_id
LEFT JOIN staffs st               ON st.staff_id = o.staff_id
LEFT JOIN customers c             ON c.customer_id = o.customer_id;
"""


class BuildError(Exception):
    """Error controlado durante la construcción o validación de la BD."""


# ---------------------------------------------------------------------------
# Lectura y limpieza
# ---------------------------------------------------------------------------

def csv_path(data_dir: Path, table: str) -> Path:
    return Path(data_dir) / f"{table}.csv"


def check_csvs_exist(data_dir: Path) -> None:
    missing = [csv_path(data_dir, t).name for t in TABLES if not csv_path(data_dir, t).is_file()]
    if missing:
        raise BuildError(
            f"Faltan CSV obligatorios en {data_dir}: {', '.join(missing)}. "
            "Copia los 9 archivos de Bike Stores a esa carpeta y vuelve a intentarlo."
        )


def read_raw_csv(path: Path) -> pd.DataFrame:
    """Lee un CSV como texto, sin inferir tipos, con encabezados normalizados."""
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _clean_text(series: pd.Series) -> list:
    values = series.astype(str).str.strip()
    return [None if v in NULL_TOKENS else v for v in values]


def _to_numbers(values: list, table: str, col: str, kind: str) -> list:
    out, bad = [], []
    for i, v in enumerate(values):
        if v is None:
            out.append(None)
            continue
        try:
            num = float(v)
        except ValueError:
            bad.append((i + 2, v))  # +2: encabezado y base 1 -> línea del CSV
            continue
        if kind == "int":
            if not num.is_integer():
                bad.append((i + 2, v))
                continue
            out.append(int(num))
        else:
            out.append(num)
    if bad:
        ejemplos = ", ".join(f"línea {ln}: {v!r}" for ln, v in bad[:5])
        tipo = "entero" if kind == "int" else "numérico"
        raise BuildError(f"{table}.{col}: {len(bad)} valor(es) no {tipo}(s). Ejemplos: {ejemplos}")
    return out


def _detect_date_format(values: list[str]) -> str | None:
    for fmt in DATE_FORMATS:
        parsed = pd.to_datetime(pd.Series(values, dtype=object), format=fmt, errors="coerce")
        if parsed.notna().all():
            return fmt
    return None


def _to_iso_dates(values: list, table: str, col: str) -> list:
    present = [v for v in values if v is not None]
    if not present:
        return values
    fmt = _detect_date_format(present)
    if fmt is None:
        # Reporta los valores que no encajan con el formato que más filas interpreta.
        best_fmt, best_ok = DATE_FORMATS[0], -1
        for f in DATE_FORMATS:
            ok = pd.to_datetime(pd.Series(present, dtype=object), format=f, errors="coerce").notna().sum()
            if ok > best_ok:
                best_fmt, best_ok = f, ok
        parsed = pd.to_datetime(pd.Series(present, dtype=object), format=best_fmt, errors="coerce")
        bad = [v for v, p in zip(present, parsed) if pd.isna(p)]
        raise BuildError(
            f"{table}.{col}: {len(bad)} fecha(s) no interpretables (formato mayoritario "
            f"{best_fmt!r}). Ejemplos: {bad[:5]}. Formatos admitidos: {DATE_FORMATS}"
        )
    if fmt != "%Y-%m-%d":
        log.info("%s.%s: formato de fecha detectado %s -> se normaliza a YYYY-MM-DD", table, col, fmt)
    return [
        None if v is None else datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        for v in values
    ]


def load_table(data_dir: Path, table: str) -> tuple[list[str], list[tuple]]:
    """Lee y limpia el CSV de una tabla. Devuelve (columnas, filas como tuplas)."""
    path = csv_path(data_dir, table)
    spec = TABLES[table]
    df = read_raw_csv(path)

    missing_cols = [c for c in spec if c not in df.columns]
    if missing_cols:
        raise BuildError(f"{path.name}: faltan las columnas {missing_cols}. Encabezados leídos: {list(df.columns)}")
    extra = [c for c in df.columns if c not in spec]
    if extra:
        log.warning("%s: se ignoran columnas no esperadas %s", path.name, extra)

    columns = {}
    for col, kind in spec.items():
        values = _clean_text(df[col])
        if kind in ("int", "real"):
            values = _to_numbers(values, table, col, kind)
        elif kind == "date":
            values = _to_iso_dates(values, table, col)
        columns[col] = values

    if table == "order_items":
        disc = columns["discount"]
        over = sum(1 for d in disc if d is not None and d > 1)
        if over:
            log.warning("order_items.discount: %d valor(es) > 1; se interpretan como porcentaje y se dividen entre 100", over)
            columns["discount"] = [d / 100 if d is not None and d > 1 else d for d in disc]

    names = list(spec)
    rows = list(zip(*(columns[c] for c in names)))
    return names, rows


# ---------------------------------------------------------------------------
# Construcción
# ---------------------------------------------------------------------------

def connect(db_path: Path) -> sqlite3.Connection:
    """Abre una conexión con llaves foráneas activas (el PRAGMA es por conexión)."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def needs_rebuild(data_dir: Path, db_path: Path) -> bool:
    db_path = Path(db_path)
    if not db_path.is_file():
        return True
    db_mtime = db_path.stat().st_mtime
    return any(
        csv_path(data_dir, t).is_file() and csv_path(data_dir, t).stat().st_mtime > db_mtime
        for t in TABLES
    )


def _remove_tmp(tmp_path: Path) -> None:
    for p in (tmp_path, tmp_path.with_name(tmp_path.name + "-journal")):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def _populate(conn: sqlite3.Connection, data: dict[str, tuple[list[str], list[tuple]]]) -> None:
    conn.execute("BEGIN")
    try:
        # Diferir las FK hasta el COMMIT permite autorreferencias (staffs.manager_id)
        # sin depender del orden de las filas.
        conn.execute("PRAGMA defer_foreign_keys = ON")
        for table, (cols, rows) in data.items():
            placeholders = ", ".join("?" for _ in cols)
            conn.executemany(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})", rows
            )
            log.info("  %-12s %6d filas insertadas", table, len(rows))
        conn.executemany(
            "INSERT INTO order_status_lookup (order_status, status_label) VALUES (?, ?)",
            sorted(config.ORDER_STATUS.items()),
        )

        ref_date, min_date = conn.execute(
            "SELECT MAX(order_date), MIN(order_date) FROM orders"
        ).fetchone()
        last_completed = conn.execute(
            "SELECT MAX(order_date) FROM orders WHERE order_status = 4"
        ).fetchone()[0]
        meta = {
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reference_date": ref_date,
            "min_order_date": min_date,
            "last_completed_date": last_completed,
        }
        for table in list(TABLES) + ["order_status_lookup"]:
            meta[f"rows.{table}"] = str(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        conn.executemany("INSERT INTO db_metadata (key, value) VALUES (?, ?)", meta.items())

        violations = _fk_violations(conn)
        if violations:
            raise BuildError("Violaciones de llave foránea:\n  " + "\n  ".join(violations[:20]))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def build_database(data_dir: Path = config.DATA_DIR, db_path: Path = config.DB_PATH,
                   force: bool = False) -> bool:
    """Construye la BD. Devuelve True si se construyó y False si ya estaba al día."""
    data_dir, db_path = Path(data_dir), Path(db_path)
    check_csvs_exist(data_dir)

    if not force and not needs_rebuild(data_dir, db_path):
        log.info("La BD %s está al día; no se reconstruye (usa --force para forzar).", db_path.name)
        return False

    log.info("Leyendo CSV desde %s", data_dir)
    data = {table: load_table(data_dir, table) for table in TABLES}
    expected = {table: len(rows) for table, (_, rows) in data.items()}

    tmp_path = db_path.with_name(db_path.name + ".tmp")
    _remove_tmp(tmp_path)
    log.info("Construyendo en %s", tmp_path.name)
    conn = None
    try:
        conn = connect(tmp_path)
        conn.isolation_level = None  # control manual de transacciones
        conn.executescript(SCHEMA_SQL)
        _populate(conn, data)

        report = validate(conn, expected)
        print(format_report(report))
        if not report.ok:
            raise BuildError("La validación falló:\n  " + "\n  ".join(report.errors))
        conn.close()
        conn = None
        os.replace(tmp_path, db_path)
    except BaseException:
        if conn is not None:
            conn.close()
        _remove_tmp(tmp_path)
        log.error("Construcción abortada; se conserva la BD anterior (si existía).")
        raise

    log.info("BD construida correctamente: %s", db_path)
    return True


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    tables: list[tuple[str, int | None, int, bool]] = field(default_factory=list)
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    reference_date: str | None = None
    net_revenue: float | None = None
    late_orders: int | None = None

    @property
    def errors(self) -> list[str]:
        errs = [f"{t}: esperado {e}, encontrado {a}" for t, e, a, ok in self.tables if not ok]
        errs += [f"{name}: {detail}" for name, ok, detail in self.checks if not ok]
        return errs

    @property
    def ok(self) -> bool:
        return not self.errors


def _fk_violations(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    return [f"{table} rowid={rowid} -> {parent} (fk #{fkid})" for table, rowid, parent, fkid in rows]


def expected_counts_from_csv(data_dir: Path) -> dict[str, int]:
    return {t: len(read_raw_csv(csv_path(data_dir, t))) for t in TABLES}


def validate(conn: sqlite3.Connection, expected: dict[str, int] | None) -> ValidationReport:
    rep = ValidationReport()
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731

    expected = dict(expected or {})
    expected.setdefault("order_status_lookup", len(config.ORDER_STATUS))
    for table in list(TABLES) + ["order_status_lookup"]:
        actual = q(f"SELECT COUNT(*) FROM {table}")
        exp = expected.get(table)
        rep.tables.append((table, exp, actual, exp is None or exp == actual))

    integrity = q("PRAGMA integrity_check")
    rep.checks.append(("integrity_check", integrity == "ok", str(integrity)))

    fk = _fk_violations(conn)
    rep.checks.append(("foreign_key_check", not fk,
                       "sin violaciones" if not fk else f"{len(fk)} violación(es): " + "; ".join(fk[:10])))

    lines_net = q("SELECT COALESCE(SUM(net_amount), 0) FROM v_order_lines")
    orders_net = q("SELECT COALESCE(SUM(net_total), 0) FROM v_orders")
    diff = abs(lines_net - orders_net)
    rep.checks.append(("net_amount == net_total", diff <= 0.01,
                       f"líneas={lines_net:,.2f} órdenes={orders_net:,.2f} dif={diff:.4f}"))

    bad_disc = q("SELECT COUNT(*) FROM order_items WHERE discount < 0 OR discount > 1 OR discount IS NULL")
    rep.checks.append(("0 <= discount <= 1", bad_disc == 0, f"{bad_disc} fila(s) fuera de rango"))

    bad_dates = 0
    for col in ("order_date", "required_date", "shipped_date"):
        bad_dates += q(
            f"SELECT COUNT(*) FROM orders WHERE {col} IS NOT NULL AND "
            f"({col} NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' OR date({col}) IS NOT {col})"
        )
    rep.checks.append(("fechas ISO YYYY-MM-DD", bad_dates == 0, f"{bad_dates} fecha(s) inválidas"))

    rep.reference_date = q("SELECT MAX(order_date) FROM orders")
    rep.net_revenue = orders_net
    rep.late_orders = q("SELECT COALESCE(SUM(is_late), 0) FROM v_orders")
    return rep


def format_report(rep: ValidationReport) -> str:
    out = ["", "REPORTE DE VALIDACION", "=" * 58,
           f"{'tabla':<22}{'filas CSV':>11}{'filas BD':>11}  estado", "-" * 58]
    for table, exp, actual, ok in rep.tables:
        exp_s = "-" if exp is None else str(exp)
        out.append(f"{table:<22}{exp_s:>11}{actual:>11}  {'OK' if ok else 'ERROR'}")
    out.append("-" * 58)
    for name, ok, detail in rep.checks:
        out.append(f"[{'OK' if ok else 'ERROR':<5}] {name}: {detail}")
    out.append("-" * 58)
    out.append(f"reference_date        : {rep.reference_date}")
    out.append(f"ingreso neto total    : {rep.net_revenue:,.2f}")
    out.append(f"órdenes con retraso   : {rep.late_orders}")
    out.append(f"resultado             : {'OK' if rep.ok else 'CON ERRORES'}")
    out.append("=" * 58)
    return "\n".join(out)


def check_database(data_dir: Path = config.DATA_DIR, db_path: Path = config.DB_PATH) -> ValidationReport:
    db_path = Path(db_path)
    if not db_path.is_file():
        raise BuildError(f"No existe la BD {db_path}. Ejecuta primero: python database_builder.py")
    try:
        expected = expected_counts_from_csv(data_dir)
    except FileNotFoundError:
        log.warning("No se encontraron todos los CSV en %s; se omite la comparación de conteos.", data_dir)
        expected = None
    conn = connect(db_path)
    try:
        return validate(conn, expected)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Construye y valida la base SQLite de Bike Stores.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--force", action="store_true", help="reconstruye aunque la BD esté al día")
    mode.add_argument("--check", action="store_true", help="solo valida la BD existente")
    parser.add_argument("--data-dir", type=Path, default=config.DATA_DIR, help="carpeta con los CSV")
    parser.add_argument("--db", type=Path, default=config.DB_PATH, help="ruta de la BD SQLite")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    try:
        if args.check:
            report = check_database(args.data_dir, args.db)
            print(format_report(report))
            if not report.ok:
                log.error("La BD tiene %d problema(s).", len(report.errors))
                return 1
            log.info("La BD es válida.")
        else:
            build_database(args.data_dir, args.db, force=args.force)
    except BuildError as exc:
        log.error("%s", exc)
        return 1
    except Exception:
        log.exception("Error inesperado")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
