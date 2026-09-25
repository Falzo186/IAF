"""Acceso de solo lectura a bikestores.db, compartido por el motor, las consultas
verificadas y el dashboard."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pandas as pd

import config

QUERY_TIMEOUT_S = 5.0


class QueryTimeout(RuntimeError):
    """La consulta superó el tiempo máximo de ejecución."""


def ro_connect(db_path: Path = config.DB_PATH) -> sqlite3.Connection:
    """Conexión de solo lectura (mode=ro + query_only)."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.execute("PRAGMA query_only = ON")
    return conn


def run_query(sql: str, params: dict | None = None, db_path: Path = config.DB_PATH,
              timeout: float | None = QUERY_TIMEOUT_S) -> pd.DataFrame:
    """Ejecuta una consulta de lectura con tiempo máximo (None = sin límite)."""
    conn = ro_connect(db_path)
    deadline = time.monotonic() + timeout if timeout else None
    if deadline is not None:
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        return pd.read_sql_query(sql, conn, params=params or None)
    except Exception as exc:
        if deadline is not None and time.monotonic() > deadline and "interrupt" in str(exc).lower():
            raise QueryTimeout(f"La consulta superó el tiempo máximo de {timeout:g} s.") from exc
        raise
    finally:
        conn.close()


def metadata(db_path: Path = config.DB_PATH) -> dict[str, str]:
    conn = ro_connect(db_path)
    try:
        return dict(conn.execute("SELECT key, value FROM db_metadata"))
    finally:
        conn.close()
