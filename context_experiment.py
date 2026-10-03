"""Experimento de contexto: ¿cambia el esquema que ve el modelo CUÁNTO y QUÉ falla?

Corre el golden set (básico + negocio, solo modo LLM, sin enrutador) con un modelo pequeño en
tres niveles de contexto de esquema y compara el acierto y la distribución de categorías de falla:

    sin_contexto       solo los nombres de las tablas y vistas
    actual             el contexto compacto de producción (sql_engine.build_system_prompt())
    describe_completo  PRAGMA table_info + foreign_key_list de cada tabla y vista, en formato DESCRIBE

Solo cambia el bloque "Esquema" del prompt; las reglas y los ejemplos son los mismos en los tres.
El código de producción no se toca: sql_engine.build_system_prompt acepta context_level (por
defecto "actual") y aquí se enlaza ese parámetro solo durante cada corrida. Los resultados se
documentan como salgan; este experimento NO cambia el contexto de producción.

Uso:
    python context_experiment.py                       # qwen2.5:1.5b, tres niveles
    python context_experiment.py --model llama3.2:1b --pull
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from contextlib import contextmanager
from datetime import datetime
from functools import partial
from pathlib import Path

import config
import eval_text2sql as ev
import sql_engine as se

LEVELS = list(se.CONTEXT_LEVELS)
LEVEL_NAMES = {
    "sin_contexto": "A · sin_contexto",
    "actual": "B · actual (producción)",
    "describe_completo": "C · describe_completo",
}
EXPERIMENT_LEVELS = ["basico", "negocio"]
OUT_MD = ev.EVAL_DIR / "experimento_contexto.md"
OUT_JSON = ev.EVAL_DIR / "experimento_contexto.json"


@contextmanager
def context_level(level: str):
    """Enlaza build_system_prompt al nivel de contexto solo mientras dura el bloque."""
    original = se.build_system_prompt
    se.build_system_prompt = partial(original, context_level=level)
    try:
        yield
    finally:
        se.build_system_prompt = original


def run_experiment(model: str, llm, items: list[dict], levels: list[str] = LEVELS,
                   on_level_done=None) -> list[dict]:
    selected = [it for it in items if it["nivel"] in EXPERIMENT_LEVELS]
    results, ref_cache = [], {}
    for level in levels:
        with context_level(level):
            for item in selected:
                res = ev.run_item(item, model, "llm", llm, ref_cache)
                res["contexto"] = level
                results.append(res)
                mark = "OK " if res["ok"] else "MAL"
                print(f"[{mark}] {level:<18} {item['id']:<4} {res['latencia_s']:>6.1f}s "
                      f"{'' if res['ok'] else str(res['fallo_categoria'])}", flush=True)
        if on_level_done:
            on_level_done(results)
    return results


def context_sizes() -> dict[str, dict[str, int]]:
    """Tokens aproximados del bloque de esquema y del prompt de sistema completo, por nivel."""
    sizes = {}
    for level in LEVELS:
        sizes[level] = {
            "esquema": se.estimate_tokens(se.get_schema_context_level(level)),
            "prompt": se.estimate_tokens(se.build_system_prompt(context_level=level)),
        }
    return sizes


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.0f} %" if total else "—"


def build_experiment_report(results: list[dict], model: str, sizes: dict) -> str:
    present = [lv for lv in LEVELS if any(r["contexto"] == lv for r in results)]
    by = {lv: [r for r in results if r["contexto"] == lv] for lv in present}
    out = [f"# Experimento de contexto de esquema ({model})", "",
           f"- Fecha: {datetime.now():%Y-%m-%d %H:%M}",
           f"- Equipo: {platform.platform()} · Python {platform.python_version()}",
           "- Golden set básico + negocio (20 ítems), solo LLM, sin enrutador, mismas reglas y ejemplos en "
           "los tres niveles; solo cambia el bloque de esquema. Exactitud por ejecución "
           "(`eval_text2sql.py`).", "",
           "## Acierto y tamaño del contexto", "",
           "| Nivel de contexto | Básico | Negocio | Total | % acierto | Tokens del esquema (aprox.) "
           "| Tokens del prompt (aprox.) | Con reintento |",
           "|---|---|---|---|---:|---:|---:|---:|"]
    for lv in present:
        rows = by[lv]
        ok = sum(r["ok"] for r in rows)
        out.append(f"| {LEVEL_NAMES[lv]} | {ev._score(rows, 'basico')} | {ev._score(rows, 'negocio')} "
                   f"| {ok}/{len(rows)} | {_pct(ok, len(rows))} | {sizes[lv]['esquema']:,} "
                   f"| {sizes[lv]['prompt']:,} | {sum(r['intentos'] == 2 for r in rows)} |")
    out += ["", "## Distribución de categorías de falla", "",
            "Cuenta de ítems incorrectos por categoría (ver `eval_text2sql.classify_failure`). "
            "La pregunta de fondo: ¿un contexto más completo cambia QUÉ error comete el modelo, "
            "y no solo cuántos?", "",
            "| Categoría | " + " | ".join(LEVEL_NAMES[lv] for lv in present) + " |",
            "|---|" + "---:|" * len(present)]
    for cat in ev.FAILURE_CATEGORIES:
        out.append(f"| `{cat}` | " + " | ".join(
            str(sum(r.get("fallo_categoria") == cat for r in by[lv])) for lv in present) + " |")
    out.append("| **Total de fallas** | " + " | ".join(
        f"**{sum(not r['ok'] for r in by[lv])}**" for lv in present) + " |")

    out += ["", "## Detalle por ítem", "",
            "| Ítem | " + " | ".join(LEVEL_NAMES[lv] for lv in present) + " |",
            "|---|" + "---|" * len(present)]
    ids = list(dict.fromkeys(r["id"] for r in results))
    for item_id in ids:
        cells = []
        for lv in present:
            r = next((r for r in by[lv] if r["id"] == item_id), None)
            cells.append("—" if r is None else "✅" if r["ok"] else f"❌ `{r['fallo_categoria']}`")
        out.append(f"| {item_id} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def verdict(results: list[dict]) -> str:
    """Frase de conclusión con los números, generada a partir de los datos."""
    acc = {lv: sum(r["ok"] for r in results if r["contexto"] == lv) for lv in LEVELS}
    n = {lv: sum(r["contexto"] == lv for r in results) for lv in LEVELS}
    if not all(n.values()):
        return "Faltan niveles por correr."
    better = acc["describe_completo"] > acc["actual"]
    return (f"describe_completo {acc['describe_completo']}/{n['describe_completo']} frente a actual "
            f"{acc['actual']}/{n['actual']}: "
            + ("mejora; revisar la distribución de fallas antes de adoptarlo."
               if better else "NO mejora, así que no se adopta en producción."))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Experimento de nivel de contexto de esquema.")
    ap.add_argument("--model", default=config.DEFAULT_MODEL)
    ap.add_argument("--pull", action="store_true", help="descarga el modelo si falta")
    ap.add_argument("--out", type=Path, default=OUT_MD)
    args = ap.parse_args(argv)

    import ollama_manager as om
    if not om.is_server_up() and not om.try_start_server():
        print(f"Ollama no está disponible en {config.OLLAMA_HOST}. Instálalo desde https://ollama.com.")
        return 2
    if not om.is_model_available(args.model):
        if not args.pull:
            print(f"{args.model} no está descargado (usa --pull).")
            return 2
        for p in om.pull_model(args.model):
            if p["percent"] is not None:
                print(f"\r  {p['status']:<30} {p['percent']:5.1f}%", end="", flush=True)
        print()

    items = ev.load_golden()
    sizes = context_sizes()

    def save(partial_results):
        args.out.write_text(build_experiment_report(partial_results, args.model, sizes), encoding="utf-8")
        args.out.with_suffix(".json").write_text(
            json.dumps(partial_results, ensure_ascii=False, indent=2), encoding="utf-8")

    results = run_experiment(args.model, om.chat, items, on_level_done=save)
    om.unload_model(args.model)
    save(results)
    print(f"\n{verdict(results)}\nReporte escrito en {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
