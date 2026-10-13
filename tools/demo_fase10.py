"""Evidencia real de la fase 10 con qwen2.5:1.5b (requiere Ollama).

Uso:  python tools/demo_fase10.py  → docs/fase10_demo.json
1. Crítica del juez en bruto vs. la que llega al siguiente intento (sin SQL).
2. N6 con "Redacción con IA": síntesis con el prompt anterior (sin total_real) vs. la actual.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

import config  # noqa: E402
import feedback as fb  # noqa: E402
import judge  # noqa: E402
import ollama_manager as om  # noqa: E402
import sql_engine as se  # noqa: E402
from business_queries import BY_ID, render_sql, run_business_query  # noqa: E402

MODEL = config.DEFAULT_MODEL
QUESTIONS = yaml.safe_load((ROOT / "reference_answers.yaml").read_text(encoding="utf-8"))

# Intentos fallidos reales de qwen (fase 8/9) para pedirle la crítica al juez.
FAILED = [
    ("N8", "SELECT store_name AS tienda, AVG(net_amount) AS gasto_promedio FROM v_order_lines "
           "WHERE order_status = 4 GROUP BY store_name"),
    ("N3", "SELECT staff_name AS vendedor, SUM(net_amount) AS ingreso FROM v_order_lines "
           "WHERE brand_name = 'Electric Bikes' AND order_status = 4 GROUP BY staff_name"),
    ("N5", "SELECT store_name, COUNT(*) AS ordenes FROM v_orders WHERE is_late = 1 GROUP BY store_name"),
    ("N2", "SELECT product_name, SUM(quantity) AS stock FROM stocks JOIN products USING (product_id) "
           "GROUP BY product_name ORDER BY stock LIMIT 10"),
]


def critiques() -> list[dict]:
    out = []
    for need, sql in FAILED:
        q = QUESTIONS[need]["pregunta"]
        ref = se.reference_for(BY_ID[need])
        try:
            df, error = se.execute_sql(se.validate_sql(sql)), None
        except Exception as exc:  # noqa: BLE001
            df, error = None, str(exc)
        raw_holder = {}

        def spy(model, messages, **opts):
            raw_holder["raw"] = om.chat(model, messages, **opts)
            return raw_holder["raw"]
        judge.critique(q, sql, df, error, MODEL, llm=spy, exclude_need=need)
        raw = raw_holder.get("raw", "")
        out.append({"necesidad": need, "sql_fallida": sql, "critica_en_bruto": raw,
                    "trae_sql": "select" in raw.lower() or "```" in raw,
                    "critica_que_llega_al_modelo": fb.sanitize(raw, ref.df)})
        print(need, "SQL en bruto:", out[-1]["trae_sql"], flush=True)
    return out


def n6() -> dict:
    q = QUESTIONS["N6"]["pregunta"]
    bq = BY_ID["N6"]
    sql, df = render_sql(bq), run_business_query(bq)
    key_fact = se.template_answer(df, "N6")
    old = om.chat(MODEL, se.build_synthesis_messages(q, sql, df, key_fact), **se.SYNTH_OPTIONS)
    new, _ = se.synthesize(q, sql, df, MODEL, om.chat, "N6")
    totals = se.compute_totals(q, df)
    return {"pregunta": q, "filas": len(df), "filas_mostradas_al_llm": min(len(df), se.SYNTH_ROWS),
            "total_real": totals, "suma_de_las_filas_mostradas": float(df["valor_inmovilizado"].head(se.SYNTH_ROWS).sum()),
            "hallazgo_determinista": key_fact, "antes_sin_total_real": se._THINK_RE.sub("", old).strip(),
            "ahora": new}


if __name__ == "__main__":
    result = {"modelo": MODEL, "criticas": critiques(), "n6": n6()}
    out = ROOT / "docs" / "fase10_demo.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["n6"], ensure_ascii=False, indent=2))
