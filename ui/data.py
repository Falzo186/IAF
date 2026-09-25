"""Lecturas cacheadas para la UI (st.cache_data). Las fechas se pasan como texto ISO."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import analytics
import db


@st.cache_data(show_spinner=False)
def metadata() -> dict:
    return db.metadata()


@st.cache_data(show_spinner=False)
def default_period() -> tuple[date, date]:
    return analytics.default_period()


@st.cache_data(show_spinner=False)
def stores() -> list[str]:
    return db.run_query("SELECT store_name FROM stores ORDER BY store_name")["store_name"].tolist()


@st.cache_data(show_spinner=False)
def kpis(store: str | None, date_from: str, date_to: str) -> dict:
    return analytics.get_kpis(store, date_from, date_to)


@st.cache_data(show_spinner=False)
def monthly(store: str | None, date_from: str, date_to: str) -> pd.DataFrame:
    return analytics.monthly_revenue(store, date_from, date_to)


@st.cache_data(show_spinner=False)
def need(bq_id: str, store: str | None, date_from: str, date_to: str) -> pd.DataFrame:
    return analytics.need(bq_id, store, date_from, date_to)
