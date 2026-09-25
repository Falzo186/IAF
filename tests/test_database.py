"""Pruebas de database_builder: construcción, idempotencia, FK y fórmulas."""

import os
import shutil
import sqlite3
import time

import pandas as pd
import pytest

import config
import database_builder as dbb


@pytest.fixture(scope="module")
def built_db(tmp_path_factory):
    """BD construida desde cero en un directorio temporal a partir de los CSV reales."""
    db_path = tmp_path_factory.mktemp("db") / "bikestores.db"
    assert dbb.build_database(config.DATA_DIR, db_path, force=False) is True
    return db_path


@pytest.fixture
def data_copy(tmp_path):
    """Copia de los CSV para pruebas que los modifican."""
    dest = tmp_path / "csv"
    shutil.copytree(config.DATA_DIR, dest)
    return dest


def _csv(name):
    return pd.read_csv(config.DATA_DIR / f"{name}.csv", encoding="utf-8-sig")


# --- Construcción desde cero -------------------------------------------------

def test_build_from_scratch(built_db):
    assert built_db.is_file()
    assert not built_db.with_name(built_db.name + ".tmp").exists()

    conn = dbb.connect(built_db)
    try:
        for table in dbb.TABLES:
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert n == len(_csv(table)), table
        views = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
        assert {"v_order_lines", "v_orders"} <= views
        meta = dict(conn.execute("SELECT key, value FROM db_metadata"))
        assert meta["reference_date"] == _csv("orders")["order_date"].max()
        assert meta["rows.orders"] == str(len(_csv("orders")))
    finally:
        conn.close()

    report = dbb.check_database(config.DATA_DIR, built_db)
    assert report.ok, report.errors


def test_last_completed_date(built_db):
    orders = _csv("orders")
    expected = orders.loc[orders["order_status"] == 4, "order_date"].max()
    conn = dbb.connect(built_db)
    try:
        value = conn.execute(
            "SELECT value FROM db_metadata WHERE key = 'last_completed_date'"
        ).fetchone()[0]
        assert value == expected
        assert value <= conn.execute(
            "SELECT value FROM db_metadata WHERE key = 'reference_date'"
        ).fetchone()[0]
    finally:
        conn.close()


def test_nulls_are_real_nulls(built_db):
    conn = dbb.connect(built_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM customers WHERE phone = 'NULL'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM orders WHERE shipped_date IS NULL").fetchone()[0] > 0
        assert conn.execute("SELECT manager_id FROM staffs WHERE staff_id = 1").fetchone()[0] is None
    finally:
        conn.close()


# --- Idempotencia ------------------------------------------------------------

def test_idempotent_without_force(tmp_path):
    db_path = tmp_path / "bikestores.db"
    assert dbb.build_database(config.DATA_DIR, db_path) is True
    mtime = db_path.stat().st_mtime_ns

    assert dbb.build_database(config.DATA_DIR, db_path) is False
    assert db_path.stat().st_mtime_ns == mtime

    assert dbb.build_database(config.DATA_DIR, db_path, force=True) is True


def test_rebuilds_when_csv_is_newer(tmp_path, data_copy):
    db_path = tmp_path / "bikestores.db"
    dbb.build_database(data_copy, db_path)
    future = time.time() + 60
    os.utime(data_copy / "brands.csv", (future, future))
    assert dbb.needs_rebuild(data_copy, db_path)
    assert dbb.build_database(data_copy, db_path) is True


# --- Llaves foráneas ---------------------------------------------------------

def test_foreign_keys_enforced(built_db):
    conn = dbb.connect(built_db)
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO order_items (order_id, item_id, product_id, quantity, list_price, discount) "
                "VALUES (999999, 1, 1, 1, 100.0, 0.1)"
            )
    finally:
        conn.rollback()
        conn.close()


def test_order_status_check_constraint(built_db):
    conn = dbb.connect(built_db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE orders SET order_status = 9 WHERE order_id = 1")
    finally:
        conn.rollback()
        conn.close()


# --- Fórmulas de las vistas --------------------------------------------------

def test_net_amount_matches_pandas(built_db):
    items = _csv("order_items")
    items["net"] = items["list_price"] * items["quantity"] * (1 - items["discount"])
    expected_by_order = items.groupby("order_id")["net"].sum()

    conn = dbb.connect(built_db)
    try:
        total_lines = conn.execute("SELECT SUM(net_amount) FROM v_order_lines").fetchone()[0]
        by_order = pd.read_sql_query("SELECT order_id, net_total FROM v_orders", conn).set_index("order_id")
    finally:
        conn.close()

    assert total_lines == pytest.approx(items["net"].sum(), abs=0.01)
    joined = by_order.join(expected_by_order, how="left").fillna(0)
    assert (joined["net_total"] - joined["net"]).abs().max() < 0.01


def test_late_orders_match_pandas(built_db):
    orders = _csv("orders")
    shipped = orders[orders["shipped_date"].notna()]
    expected = (pd.to_datetime(shipped["shipped_date"]) > pd.to_datetime(shipped["required_date"])).sum()

    conn = dbb.connect(built_db)
    try:
        late = conn.execute("SELECT SUM(is_late) FROM v_orders").fetchone()[0]
        unshipped_late = conn.execute(
            "SELECT COUNT(*) FROM v_orders WHERE is_shipped = 0 AND (is_late = 1 OR days_late IS NOT NULL)"
        ).fetchone()[0]
    finally:
        conn.close()
    assert late == expected
    assert unshipped_late == 0


# --- Limpieza de datos -------------------------------------------------------

def test_dates_normalized_and_discount_percent(tmp_path, data_copy):
    orders = pd.read_csv(data_copy / "orders.csv", dtype=str, keep_default_na=False)
    for col in ("order_date", "required_date"):
        orders[col] = pd.to_datetime(orders[col]).dt.strftime("%d/%m/%Y")
    orders.to_csv(data_copy / "orders.csv", index=False)

    items = pd.read_csv(data_copy / "order_items.csv")
    items.loc[0, "discount"] = 20  # 20 % expresado como porcentaje
    items.to_csv(data_copy / "order_items.csv", index=False)

    db_path = tmp_path / "bikestores.db"
    dbb.build_database(data_copy, db_path)
    conn = dbb.connect(db_path)
    try:
        assert conn.execute("SELECT order_date FROM orders WHERE order_id = 1").fetchone()[0] == "2016-01-01"
        assert conn.execute(
            "SELECT discount FROM order_items WHERE order_id = 1 AND item_id = 1"
        ).fetchone()[0] == pytest.approx(0.2)
    finally:
        conn.close()


# --- Errores y atomicidad ----------------------------------------------------

def test_missing_csv_fails(tmp_path, data_copy):
    (data_copy / "orders.csv").unlink()
    with pytest.raises(dbb.BuildError, match="orders.csv"):
        dbb.build_database(data_copy, tmp_path / "bikestores.db")


def test_failed_build_keeps_previous_db(tmp_path, data_copy):
    db_path = tmp_path / "bikestores.db"
    dbb.build_database(data_copy, db_path)
    before = db_path.read_bytes()

    orders = pd.read_csv(data_copy / "orders.csv", dtype=str, keep_default_na=False)
    orders.loc[0, "order_date"] = "no-es-fecha"
    orders.to_csv(data_copy / "orders.csv", index=False)

    with pytest.raises(dbb.BuildError, match="order_date"):
        dbb.build_database(data_copy, db_path, force=True)
    assert db_path.read_bytes() == before
    assert not db_path.with_name(db_path.name + ".tmp").exists()


def test_cli_exit_codes(tmp_path, data_copy):
    db_path = tmp_path / "bikestores.db"
    args = ["--data-dir", str(data_copy), "--db", str(db_path)]
    assert dbb.main(args + ["--check"]) == 1  # aún no existe la BD
    assert dbb.main(args) == 0
    assert dbb.main(args + ["--check"]) == 0
    (data_copy / "stocks.csv").unlink()
    assert dbb.main(args + ["--force"]) == 1
