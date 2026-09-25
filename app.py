"""Bike Stores: plataforma analítica y asistente Text-to-SQL.

Ejecutar:  streamlit run app.py
"""

import streamlit as st

import config

st.set_page_config(page_title="Bike Stores · Analítica", page_icon="🚲", layout="wide",
                   initial_sidebar_state="collapsed")
st.html(f"<style>{(config.BASE_DIR / 'assets' / 'style.css').read_text(encoding='utf-8')}</style>")

if not config.DB_PATH.is_file():
    st.error(
        f"No se encontró la base de datos `{config.DB_PATH.name}`. Genérala desde la carpeta del "
        "proyecto con el comando de abajo y vuelve a cargar la página."
    )
    st.code("python database_builder.py", language="bash")
    st.stop()

pages = [
    st.Page("views/dashboard.py", title="Dashboard", icon=":material/monitoring:", default=True),
    st.Page("views/asistente.py", title="Asistente", icon=":material/forum:"),
]
st.navigation(pages, position="top").run()
