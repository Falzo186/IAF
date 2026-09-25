"""Evaluación Text-to-SQL en dos niveles (básico / negocio) y dos modos.

Modos:
    llm   : solo LLM (enrutador desactivado)
    full  : sistema completo (enrutador de consultas verificadas + LLM)

Uso:
    python eval_text2sql.py                               # modelos de config.SUPPORTED_MODELS descargados
    python eval_text2sql.py --models qwen2.5:1.5b --pull  # descarga el modelo si falta
    python eval_text2sql.py --oracle                      # verifica el arnés sin Ollama (LLM = SQL de referencia)

Niveles: basico (preguntas directas), negocio (las 10 necesidades), anclada (necesidad +
filtro no soportado). En el modo "full" se genera además la síntesis ejecutiva, para medir
la latencia de la respuesta completa que verá el usuario (p50/p95). Los resultados se
fusionan con eval/resultados.json: al re-evaluar un modelo solo se reemplazan sus filas
(usa --fresh para empezar de cero).

La exactitud se mide por ejecución: se comparan los resultados de la SQL
generada con los de la SQL de referencia según el 'check' de cada ítem en
eval/golden.json (columnas clave, orden de columnas y alias irrelevantes,
números con tolerancia de 0.5 % o 0.01).
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

import config
import sql_engine as se
from business_queries import BY_ID, render_sql

EVAL_DIR = config.BASE_DIR / "eval"
GOLDEN_PATH = EVAL_DIR / "golden.json"
MODES = {"llm": "solo LLM", "full": "sistema completo"}
LEVELS = ["basico", "negocio", "anclada"]


# ---------------------------------------------------------------------------
# Golden set y comparación de resultados
# ---------------------------------------------------------------------------

def load_golden(path: Path = GOLDEN_PATH) -> list[dict]:
    items = json.loads(Path(path).read_text(encoding="utf-8"))["items"]
    for it in items:
        if it.get("business_query") and not it.get("sql"):
            it["sql"] = render_sql(BY_ID[it["business_query"]], **it.get("filters", {}))
    return items


def _norm(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return str(v).strip().casefold()


def _cell_eq(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= max(0.01, 0.005 * abs(a))
    return a == b


def _row_in(ref_row: list, got_row: list) -> bool:
    """Cada valor de la fila de referencia aparece en una celda distinta de la fila obtenida."""
    free = list(got_row)
    for v in ref_row:
        idx = next((i for i, g in enumerate(free) if _cell_eq(v, g)), None)
        if idx is None:
            return False
        free.pop(idx)
    return True


def compare_results(ref: pd.DataFrame, got: pd.DataFrame | None, check: dict) -> tuple[bool, str]:
    if got is None:
        return False, "sin resultado"
    key_cols = check.get("key_columns") or list(ref.columns)
    ref_rows = [[_norm(v) for v in row] for row in ref[key_cols].itertuples(index=False)]
    got_rows = [[_norm(v) for v in row] for row in got.itertuples(index=False)]

    mode = check.get("mode", "exact")
    if mode == "exact":
        if len(got_rows) != len(ref_rows):
            return False, f"filas: esperadas {len(ref_rows)}, obtenidas {len(got_rows)}"
        targets = ref_rows
    else:
        targets = ref_rows[: check.get("k", 1)]

    available = list(range(len(got_rows)))
    for n, ref_row in enumerate(targets):
        hit = next((i for i in available if _row_in(ref_row, got_rows[i])), None)
        if hit is None:
            return False, f"fila de referencia {n + 1} no encontrada: {ref_row}"
        available.remove(hit)
    return True, "ok"


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------

def oracle_llm(items: list[dict]):
    """LLM falso que responde con la SQL de referencia (para verificar el arnés)."""
    by_question = {it["pregunta"]: it["sql"] for it in items}

    def llm(model, messages, **_):
        question = messages[-1]["content"]
        return f"```sql\n{by_question[question]}\n```"
    return llm


def run_item(item: dict, model: str, mode: str, llm, ref_cache: dict) -> dict:
    if item["id"] not in ref_cache:
        ref_cache[item["id"]] = se.execute_sql(se.validate_sql(item["sql"]))
    ref = ref_cache[item["id"]]

    full = mode == "full"
    t0 = time.perf_counter()
    r = se.answer_question(item["pregunta"], model, llm=llm, use_router=full, synthesize_answer=full)
    total = time.perf_counter() - t0
    ok, reason = (False, r.error or "error") if r.error else compare_results(ref, r.df, item["check"])
    return {
        "id": item["id"], "nivel": item["nivel"], "modelo": model, "modo": mode,
        "ok": ok, "motivo": reason, "fuente": r.source, "consulta_verificada": r.business_query_id,
        "intentos": r.attempts, "latencia_s": round(total - r.timings["synth"], 2),
        "latencia_total_s": round(total, 2) if full else None,
        "sql": r.sql, "respuesta": r.answer if full else None,
    }


def evaluate(models: list[str], modes: list[str], levels: list[str], items: list[dict],
             llm_factory) -> list[dict]:
    results, ref_cache = [], {}
    selected = [it for it in items if it["nivel"] in levels]
    for model in models:
        llm = llm_factory(model)
        for mode in modes:
            for item in selected:
                res = run_item(item, model, mode, llm, ref_cache)
                results.append(res)
                mark = "OK " if res["ok"] else "MAL"
                print(f"[{mark}] {model:<18} {mode:<4} {item['id']:<4} {res['latencia_s']:>6.1f}s "
                      f"{res['fuente']:<10} {'' if res['ok'] else res['motivo'][:70]}", flush=True)
    return results


# ---------------------------------------------------------------------------
# Reporte
# ---------------------------------------------------------------------------

def percentile(values: list[float], q: float) -> float:
    """Percentil por rango más cercano (q en 0..100)."""
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    k = max(0, min(len(ordered) - 1, int(-(-q * len(ordered) // 100)) - 1))
    return ordered[k]


def _score(rows: list[dict], level: str) -> str:
    subset = [r for r in rows if r["nivel"] == level]
    return f"{sum(r['ok'] for r in subset)}/{len(subset)}" if subset else "-"


def build_report(results: list[dict], models: list[str], modes: list[str], skipped: dict,
                 title: str) -> str:
    out = [f"# {title}", "",
           f"- Fecha: {datetime.now():%Y-%m-%d %H:%M}",
           f"- Equipo: {platform.platform()} · Python {platform.python_version()}",
           f"- Ollama: {config.OLLAMA_HOST}",
           "- Exactitud por ejecución (ver `eval_text2sql.py`). *Latencia SQL* = enrutar + generar + "
           "validar + ejecutar. *Respuesta completa* = lo que espera el usuario (incluye la síntesis); "
           "solo se mide en el modo sistema completo.", "",
           "## Resumen", "",
           "| Modelo | Modo | Básico | Negocio | Anclada | Latencia SQL media (s) "
           "| Respuesta completa p50 (s) | Respuesta completa p95 (s) | Con reintento |",
           "|---|---|---|---|---|---:|---:|---:|---:|"]
    for model in models:
        for mode in modes:
            rows = [r for r in results if r["modelo"] == model and r["modo"] == mode]
            if not rows:
                continue
            lat = [r["latencia_s"] for r in rows]
            tot = [r["latencia_total_s"] for r in rows if r.get("latencia_total_s") is not None]
            p50 = f"{percentile(tot, 50):.1f}" if tot else "—"
            p95 = f"{percentile(tot, 95):.1f}" if tot else "—"
            retries = sum(r["intentos"] == 2 for r in rows)
            out.append(f"| {model} | {MODES[mode]} | {_score(rows, 'basico')} | {_score(rows, 'negocio')} "
                       f"| {_score(rows, 'anclada')} | {statistics.mean(lat):.1f} | {p50} | {p95} | {retries} |")
    for model, why in skipped.items():
        out.append(f"| {model} | — | no evaluado | no evaluado | no evaluado | — | — | — | — |")
    if skipped:
        out += ["", *[f"- `{m}` no se evaluó: {why}" for m, why in skipped.items()]]

    qwen = [r for r in results if r["modelo"] == config.DEFAULT_MODEL]
    if qwen:
        basic_llm = [r for r in qwen if r["modo"] == "llm" and r["nivel"] == "basico"]
        biz_full = [r for r in qwen if r["modo"] == "full" and r["nivel"] == "negocio"]
        out += ["", f"## Criterios de aceptación ({config.DEFAULT_MODEL})", ""]
        if basic_llm:
            n = sum(r["ok"] for r in basic_llm)
            out.append(f"- Básico, solo LLM >= 8/10: **{n}/{len(basic_llm)}** "
                       f"{'CUMPLE' if n >= 8 else 'NO CUMPLE'}")
        if biz_full:
            n = sum(r["ok"] for r in biz_full)
            out.append(f"- Negocio, sistema completo = 10/10: **{n}/{len(biz_full)}** "
                       f"{'CUMPLE' if n == len(biz_full) == 10 else 'NO CUMPLE'}")

    out += ["", "## Detalle", "",
            "| Modelo | Modo | Ítem | Resultado | Fuente | Intentos | Latencia SQL (s) | Total (s) | Motivo |",
            "|---|---|---|---|---|---:|---:|---:|---|"]
    for r in results:
        motivo = "" if r["ok"] else str(r["motivo"]).replace("|", "/").replace("\n", " ")[:90]
        total = "" if r.get("latencia_total_s") is None else f"{r['latencia_total_s']:.1f}"
        out.append(f"| {r['modelo']} | {MODES[r['modo']]} | {r['id']} | {'✅' if r['ok'] else '❌'} "
                   f"| {r['fuente']} | {r['intentos']} | {r['latencia_s']:.1f} | {total} | {motivo} |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evalúa el motor Text-to-SQL.")
    ap.add_argument("--models", nargs="+", default=config.SUPPORTED_MODELS)
    ap.add_argument("--modes", nargs="+", choices=list(MODES), default=list(MODES))
    ap.add_argument("--levels", nargs="+", choices=LEVELS, default=LEVELS)
    ap.add_argument("--pull", action="store_true", help="descarga los modelos que falten")
    ap.add_argument("--oracle", action="store_true", help="usa la SQL de referencia como LLM (sin Ollama)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--fresh", action="store_true", help="no fusionar con resultados previos")
    args = ap.parse_args(argv)

    items = load_golden()
    skipped: dict[str, str] = {}

    if args.oracle:
        models = ["oraculo"]
        llm_factory = lambda _m: oracle_llm(items)  # noqa: E731
        out = args.out or EVAL_DIR / "resultados_oraculo.md"
        title = "Verificación del arnés de evaluación (oráculo, sin LLM)"
    else:
        import ollama_manager as om
        if not om.is_server_up() and not om.try_start_server():
            print("Ollama no está disponible (no instalado o sin responder en "
                  f"{config.OLLAMA_HOST}). Instálalo desde https://ollama.com y vuelve a ejecutar.")
            return 2
        models = []
        for m in args.models:
            if om.is_model_available(m):
                models.append(m)
            elif args.pull:
                print(f"Descargando {m}...")
                for p in om.pull_model(m):
                    if p["percent"] is not None:
                        print(f"\r  {p['status']:<30} {p['percent']:5.1f}%", end="", flush=True)
                print()
                models.append(m)
            else:
                skipped[m] = "no está descargado (usa --pull)"

        def llm_factory(model):
            return om.chat
        out = args.out or EVAL_DIR / "resultados.md"
        title = "Resultados de la evaluación Text-to-SQL"

    json_path = out.with_suffix(".json")
    results = []
    if not args.fresh and json_path.exists():
        # Conserva los resultados de otros modelos/modos; se reemplazan los que se re-evalúan.
        ids = {it["id"] for it in items if it["nivel"] in args.levels}
        rerun = {(m, mode, i) for m in models for mode in args.modes for i in ids}
        results = [r for r in json.loads(json_path.read_text(encoding="utf-8"))
                   if (r["modelo"], r["modo"], r["id"]) not in rerun]

    item_order = {it["id"]: i for i, it in enumerate(items)}

    def save():
        all_models = list(dict.fromkeys([r["modelo"] for r in results] + models))
        results.sort(key=lambda r: (all_models.index(r["modelo"]), list(MODES).index(r["modo"]),
                                    item_order.get(r["id"], 999)))
        modes = [m for m in MODES if any(r["modo"] == m for r in results)]
        out.write_text(build_report(results, all_models, modes, skipped, title), encoding="utf-8")
        json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    previous = None
    for model in models:
        if previous and not args.oracle:
            om.unload_model(previous)  # desactivación dinámica: libera la RAM del anterior
        results += evaluate([model], args.modes, args.levels, items, llm_factory)
        save()  # guarda tras cada modelo para no perder trabajo si algo falla
        previous = model
    if previous and not args.oracle:
        om.unload_model(previous)

    save()
    print(f"\nReporte escrito en {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
