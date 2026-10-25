"""Página de solo lectura: resultados del experimento de la fase 11 (eval/fase11/resultados.json).

No ejecuta nada: muestra lo que dejó `python eval_fase11.py`. Si el archivo no existe, explica cómo
generarlo.
"""

import json

import pandas as pd
import streamlit as st

import config

RESULTS = config.BASE_DIR / "eval" / "fase11" / "resultados.json"
CHART = RESULTS.with_name("grafica_comparativa.png")
MODOS = [("base", "Base"), ("fewshot", "Few shot"), ("rag", "RAG"), ("harness", "Harness")]
CONJUNTOS = {"golden": "Golden (24)", "negativas_heldout": "Heldout"}

st.markdown("## Comparativa Fase 11")
st.caption("Base | Few shot | RAG | Harness, medido con los modelos locales y el comparador determinista. "
           "Solo lectura: se regenera con `python eval_fase11.py`.")

if not RESULTS.is_file():
    st.info("Todavía no hay resultados. Ejecuta `python eval_fase11.py` (necesita Ollama y los modelos "
            "descargados) y vuelve a cargar esta página.")
    st.stop()

try:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
except (OSError, ValueError):
    st.error("No se pudo leer eval/fase11/resultados.json.")
    st.stop()
meta, rows = data.get("meta", {}), pd.DataFrame(data.get("resultados", []))

if meta.get("simulado"):
    st.warning("Estos resultados son SIMULADOS (prueba de humo): no representan a ningún modelo.")
if rows.empty:
    st.info("El archivo de resultados está vacío.")
    st.stop()

st.markdown(f"<span class='badge badge-offline'>red: {meta.get('red', '?')} · conexiones externas: "
            f"{meta.get('conexiones_externas', 'n/d')}</span>", unsafe_allow_html=True)
st.caption(f"{meta.get('fecha', '')} · commit {meta.get('commit', '')} · catálogo {meta.get('catalogo_hash', '')} "
           f"· política oficial: sin_gemelas (la SQL de la respuesta nunca llega al modelo)")


def pct(df: pd.DataFrame) -> str:
    return f"{int(df['ok'].sum())}/{len(df)} ({100 * df['ok'].mean():.0f} %)" if len(df) else "—"


table = []
for model in dict.fromkeys(rows["modelo"]):
    for key, label in CONJUNTOS.items():
        line = {"Modelo": model, "Conjunto": label}
        for modo, name in MODOS:
            sel = rows[(rows["modelo"] == model) & (rows["modo"] == modo) & (rows["conjunto"] == key)
                       & (rows["politica"] == ("n/a" if modo == "base" else "sin_gemelas"))]
            line[name] = pct(sel)
        table.append(line)
st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")

if CHART.is_file():
    st.image(str(CHART))

with st.expander("Calidad de la SQL y costo (política oficial)"):
    official = rows[rows["politica"].isin(["n/a", "sin_gemelas"])]
    summary = (official.groupby(["modelo", "modo", "conjunto"])
               .agg(aciertos=("ok", "mean"), ejecutable=("ejecutable", "mean"),
                    columnas_inventadas=("alucina_columnas", "mean"), intentos=("intentos", "mean"),
                    p50_s=("latencia_s", "median")).reset_index())
    for col in ("aciertos", "ejecutable", "columnas_inventadas"):
        summary[col] = (100 * summary[col]).round(0).astype(int).astype(str) + " %"
    summary["intentos"], summary["p50_s"] = summary["intentos"].round(2), summary["p50_s"].round(1)
    st.dataframe(summary, hide_index=True, width="stretch")

st.caption("Detalle, políticas permisiva y estricta, categorías de falla y conclusiones: "
           "`eval/fase11/tabla_comparativa.md` y `fase11.md`.")
