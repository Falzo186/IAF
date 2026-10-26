"""Experimento de la fase 11: Base | Few shot | RAG | Harness × modelos locales × (golden, heldout).

    python eval_fase11.py --modelos qwen2.5:1.5b llama3.2:1b deepseek-r1:1.5b \\
        --modos base fewshot rag harness --conjuntos golden negativas_heldout \\
        --max-intentos 2 --repeticiones 1 --red offline --salida eval/fase11/

Modos:   base | fewshot (dinámico) | fewshot_estatico | rag | harness | harness_router
         (harness_router = sistema completo: enrutador verificado + harness; es la fila aparte).
Conjuntos: golden (24 ítems con leave-one-out) y negativas_heldout (split heldout del catálogo,
         que nunca se inyecta en un prompt).
Política de exclusión de ejemplos (qué se le oculta al modelo de la pregunta evaluada):
    sin_gemelas  (oficial) fuera la pregunta, el id y todo ejemplo cuya SQL sea idéntica a la
                 referencia: el modelo nunca ve la SQL de la respuesta, ni disfrazada de paráfrasis.
    permisivo    solo fuera la pregunta y el id (leave-one-out literal): un hermano con la misma SQL
                 SÍ puede aparecer. Es la cota superior de "reconocer una pregunta ya vista".
    estricto     sin_gemelas y además fuera todos los ejemplos de la misma necesidad: mide el
                 comportamiento ante una necesidad que el catálogo no conoce.
Reparación: "produccion" (por defecto): se reintenta solo si la SQL falla, con el error de
         SQLite/validación, como el chat real; "comparador": además corta y da feedback por
         categoría contra la referencia (solo la FORMA del problema, nunca valores).
La corrección la decide siempre eval_text2sql.compare_results. Con --red offline se bloquea y se
cuenta cualquier conexión que no sea a localhost (debe dar 0).
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import config
import eval_text2sql as ev
import fewshot
import harness
import netmode
import sql_engine as se
from necesidades_negativas import catalogo

OUT_DIR = config.BASE_DIR / "eval" / "fase11"
MODOS = {
    "base": ("base", False), "fewshot": ("fewshot", False), "fewshot_estatico": ("fewshot", False),
    "rag": ("rag", False), "harness": ("harness", False), "harness_router": ("harness", True),
}
MODO_NOMBRE = {"base": "Base", "fewshot": "Few shot", "fewshot_estatico": "Few shot (estático)",
               "rag": "RAG", "harness": "Harness", "harness_router": "Harness + router"}
CONJUNTOS = ("golden", "negativas_heldout")
POLITICAS = ("sin_gemelas", "permisivo", "estricto")
# Para ahorrar corridas: base no depende de la política; las otras políticas solo se miden en estos modos.
MODOS_POLITICA_EXTRA = ("fewshot", "rag", "harness")
SPLIT_SIN_HERMANOS = ("basico", "anclada")       # ítems del golden cuyo tipo no está en el catálogo


# ---------------------------------------------------------------------------
# Ítems
# ---------------------------------------------------------------------------

def golden_items() -> list[dict]:
    items = []
    for it in ev.load_golden():
        items.append({**it, "conjunto": "golden", "tipo": it["nivel"],
                      "necesidad": it.get("business_query") if it["nivel"] == "negocio" else None})
    return items


def heldout_items(db_path: Path = config.DB_PATH) -> list[dict]:
    """Entradas heldout del catálogo como ítems evaluables (la referencia es su propia SQL)."""
    from necesidades_negativas import validador
    cache: dict = {}
    items = []
    for r in catalogo.load_catalog(split="heldout"):
        base_df, base_check = validador.base_reference(r["necesidad_base"], db_path, cache)
        own = se.execute_sql(se.validate_sql(r["sql"], db_path), db_path)
        keys = base_check.get("key_columns") or []
        # Si la salida conserva las columnas clave de la necesidad se usa su criterio (parcial);
        # si no (otra métrica, otra tabla) se compara el resultado completo.
        check = base_check if keys and all(k in own.columns for k in keys) else {"mode": "exact"}
        items.append({"id": r["id"], "nivel": "heldout", "pregunta": r["pregunta"], "sql": r["sql"],
                      "check": check, "conjunto": "negativas_heldout", "tipo": r["tipo"],
                      "necesidad": r["necesidad_base"]})
    return items


def exclusion_opts(item: dict, politica: str) -> dict:
    opts = {"exclude_ids": [item["id"]], "exclude_questions": [item["pregunta"]]}
    if politica in ("sin_gemelas", "estricto"):
        opts["exclude_sql"] = [item["sql"]]
    if politica == "estricto" and item.get("necesidad"):
        opts["exclude_need"] = item["necesidad"]
    return opts


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------

def ollama_ram_mb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    total = 0
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            if "ollama" in (p.info["name"] or "").lower():
                total += p.info["memory_info"].rss
        except (psutil.Error, TypeError):
            continue
    return round(total / 1e6, 1)


def halluc_columns(sql: str | None, error: str | None) -> bool:
    """¿La SQL final usa una columna que no existe? (error de SQLite o validación estática)."""
    if error and "no such column" in error.lower():
        return True
    return bool(sql) and harness.check_columns(sql) is not None


def run_one(item: dict, model: str, modo: str, politica: str, llm, ref_cache: dict,
            max_intentos: int, reparacion: str, consistencia: int = 1) -> dict:
    if item["id"] not in ref_cache:
        ref_cache[item["id"]] = se.execute_sql(se.validate_sql(item["sql"]))
    ref = ref_cache[item["id"]]
    context_mode, router = MODOS[modo]
    opts = {} if modo == "base" else exclusion_opts(item, politica)
    if modo == "fewshot_estatico":
        opts["fewshot_modo"] = "estatico"
    check = ev.make_attempt_check(item, ref) if reparacion == "comparador" else None
    kwargs = dict(use_router=router, synthesize_answer=False, max_attempts=max_intentos,
                  attempt_check=check, modo_contexto=context_mode, contexto_opts=opts or None)
    t0 = time.perf_counter()
    if context_mode == "harness" and consistencia > 1:
        r = harness.run(item["pregunta"], model, None, llm, use_router=router, max_attempts=max_intentos,
                        attempt_check=check, contexto_opts=opts, consistencia=consistencia)
    else:
        r = se.answer_question(item["pregunta"], model, llm=llm, **kwargs)
    seconds = time.perf_counter() - t0
    ok, reason = (False, r.error or "error") if r.error else ev.compare_results(ref, r.df, item["check"])
    category = detail = None
    if not ok:
        category, detail = ev.classify_failure(item, ref, r.df, r.sql, r.error, reason)
    return {
        "id": item["id"], "conjunto": item["conjunto"], "tipo": item["tipo"], "necesidad": item.get("necesidad"),
        "modelo": model, "modo": modo, "politica": politica if modo != "base" else "n/a",
        "ok": ok, "motivo": reason, "fuente": r.source, "ejecutable": r.error is None,
        "alucina_columnas": halluc_columns(r.sql, r.error), "intentos": r.attempts,
        "acerto_en_intento": (r.hit_attempt or r.attempts) if ok else None,
        "latencia_s": round(seconds, 2), "sql": r.sql, "fallo_categoria": category, "fallo_detalle": detail,
        "ejemplos": [e["id"] for e in r.ejemplos], "ejemplos_origen": sorted({e["origen"] for e in r.ejemplos}),
        "esquema_recortado": any(t.get("esquema_recortado") for t in r.traza),
        "traza_etapas": [t["etapa"] for t in r.traza],
    }


def oracle_for(items: list[dict]):
    """LLM falso para --simulado: responde con la SQL de referencia (solo pruebas de humo)."""
    by_question = {it["pregunta"]: it["sql"] for it in items}

    def llm(model, messages, **_):
        return f"```sql\n{by_question.get(messages[-1]['content'], 'SELECT 1')}\n```"
    return llm


def plan(modos: list[str], politicas: list[str]) -> list[tuple[str, str]]:
    """(modo, política) a correr. Base una sola vez; el resto de políticas solo para los modos clave."""
    out = []
    for modo in modos:
        if modo == "base":
            out.append((modo, "n/a"))
            continue
        for pol in politicas:
            if pol == "sin_gemelas" or modo in MODOS_POLITICA_EXTRA:
                out.append((modo, pol))
    return out


def run_experiment(modelos, modos, conjuntos, politicas, max_intentos, reparacion, repeticiones,
                   llm_factory, items_by_set: dict, on_progress=None, done: set | None = None,
                   consistencia: int = 1) -> list[dict]:
    results, done = [], done or set()
    ref_cache: dict = {}
    for model in modelos:
        llm = llm_factory(model)
        for modo, pol in plan(modos, politicas):
            for conjunto in conjuntos:
                for item in items_by_set[conjunto]:
                    for rep in range(repeticiones):
                        key = (model, modo, pol, conjunto, item["id"], rep)
                        if key in done:
                            continue
                        res = run_one(item, model, modo, pol, llm, ref_cache, max_intentos, reparacion, consistencia)
                        res["repeticion"] = rep
                        results.append(res)
                        mark = "OK " if res["ok"] else "MAL"
                        print(f"[{mark}] {model:<16} {modo:<16} {pol:<11} {item['id']:<10} {res['latencia_s']:>5.1f}s "
                              f"{res['fuente']:<12} {'' if res['ok'] else str(res['fallo_categoria'])}", flush=True)
            if on_progress:
                on_progress(results)       # guarda tras cada bloque (modo, política) para no perder trabajo
        ram = ollama_ram_mb()
        for r in results:
            if r["modelo"] == model and "ram_mb" not in r:
                r["ram_mb"] = ram
        if on_progress:
            on_progress(results)
    return results


# ---------------------------------------------------------------------------
# Resumen y reportes
# ---------------------------------------------------------------------------

def cell(rows: list[dict]) -> str:
    return f"{sum(r['ok'] for r in rows)}/{len(rows)} ({100 * sum(r['ok'] for r in rows) / len(rows):.0f} %)" if rows else "—"


def pick(results, **conds):
    return [r for r in results if all(r.get(k) == v for k, v in conds.items())]


def summarize(results: list[dict]) -> dict:
    """Métricas por (modelo, modo, política, conjunto)."""
    out = {}
    keys = sorted({(r["modelo"], r["modo"], r["politica"], r["conjunto"]) for r in results})
    for key in keys:
        rows = pick(results, modelo=key[0], modo=key[1], politica=key[2], conjunto=key[3])
        lat = [r["latencia_s"] for r in rows]
        out["|".join(key)] = {
            "modelo": key[0], "modo": key[1], "politica": key[2], "conjunto": key[3], "n": len(rows),
            "aciertos": sum(r["ok"] for r in rows), "pct": round(100 * sum(r["ok"] for r in rows) / len(rows), 1),
            "ejecutable_pct": round(100 * sum(r["ejecutable"] for r in rows) / len(rows), 1),
            "alucina_columnas_pct": round(100 * sum(r["alucina_columnas"] for r in rows) / len(rows), 1),
            "intentos_prom": round(statistics.mean(r["intentos"] for r in rows), 2),
            "latencia_p50": round(ev.percentile(lat, 50), 1), "latencia_p95": round(ev.percentile(lat, 95), 1),
            "ram_mb": max([r.get("ram_mb") or 0 for r in rows], default=0) or None,
            "por_tipo": {t: cell(pick(rows, tipo=t)) for t in sorted({r["tipo"] for r in rows})},
            "fallas": {c: sum(r["fallo_categoria"] == c for r in rows) for c in ev.FAILURE_CATEGORIES},
        }
    return out


def comparative_table(results: list[dict], modelos: list[str], politica: str = "sin_gemelas",
                      modos: tuple = ("base", "fewshot", "rag", "harness")) -> list[str]:
    """Tabla del pizarrón: filas = modelo × conjunto, columnas = Base | Few shot | RAG | Harness."""
    header = "| Modelo | Conjunto | " + " | ".join(MODO_NOMBRE[m] for m in modos) + " |"
    out = [header, "|---|---|" + "---|" * len(modos)]
    for model in modelos:
        for conjunto, label in (("golden", "Golden (24)"), ("negativas_heldout", "Heldout")):
            cells = []
            for modo in modos:
                rows = pick(results, modelo=model, modo=modo, conjunto=conjunto,
                            politica="n/a" if modo == "base" else politica)
                cells.append(cell(rows))
            if any(c != "—" for c in cells):
                out.append(f"| {model} | {label} | " + " | ".join(cells) + " |")
    return out


def sign_test_p(wins: int, losses: int) -> float:
    """p bilateral exacta de la prueba de los signos (binomial 0.5) sobre los pares que cambiaron."""
    from math import comb
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(0, min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def paired_table(results: list[dict], modelos: list[str], politica: str = "sin_gemelas") -> list[str]:
    """Ítem por ítem frente a Base: cuántos pasaron de mal a bien (mejora) y de bien a mal (empeora)."""
    out = ["| Modelo | Conjunto | Modo | Mejoran | Empeoran | Igual | p (prueba de los signos) |",
           "|---|---|---|---:|---:|---:|---:|"]
    for model in modelos:
        for conjunto in CONJUNTOS:
            base = {r["id"]: r["ok"] for r in pick(results, modelo=model, modo="base", conjunto=conjunto)}
            if not base:
                continue
            for modo in ("fewshot", "rag", "harness", "harness_router"):
                other = {r["id"]: r["ok"] for r in pick(results, modelo=model, modo=modo, conjunto=conjunto,
                                                          politica=politica)}
                if not other:
                    continue
                ids = base.keys() & other.keys()
                wins = sum(other[i] and not base[i] for i in ids)
                losses = sum(base[i] and not other[i] for i in ids)
                out.append(f"| {model} | {conjunto} | {MODO_NOMBRE[modo]} | {wins} | {losses} "
                           f"| {len(ids) - wins - losses} | {sign_test_p(wins, losses):.3f} |")
    return out


def build_markdown(results: list[dict], meta: dict) -> str:
    modelos = list(dict.fromkeys(r["modelo"] for r in results))
    banner = ["> **SIMULADO**: el LLM es la SQL de referencia; estas cifras son una prueba de humo, no resultados.", ""] if meta.get("simulado") else []
    out = [f"# Fase 11: Base | Few shot | RAG | Harness {'(SIMULADO)' if meta.get('simulado') else ''}", "", *banner,
           f"- Fecha: {meta['fecha']} · {meta['plataforma']} · commit `{meta['commit']}`",
           f"- Modo de red: **{meta['red']}** · conexiones externas intentadas: **{meta.get('conexiones_externas', 'n/d')}**",
           f"- Catálogo `{meta['catalogo_hash']}` ({meta['catalogo_n']} ejemplos; train {meta['catalogo_train']}, "
           f"heldout {meta['catalogo_heldout']}) · golden `{meta['golden_hash']}`",
           f"- Intentos máx.: {meta['max_intentos']} · reparación: {meta['reparacion']} · repeticiones: {meta['repeticiones']} "
           f"· temperatura 0 · RAG_MIN_SCORE {meta['rag_min_score']} · FEWSHOT_MAX_CHARS {meta['fewshot_max_chars']}",
           "- Corrección por `compare_results` (determinista). Política oficial de ejemplos: **sin_gemelas** "
           "(ver docstring de `eval_fase11.py`).", "",
           "## Tabla comparativa (política oficial: sin_gemelas)", "", *comparative_table(results, modelos), ""]

    extra_modes = tuple(m for m in ("fewshot_estatico", "harness_router") if any(r["modo"] == m for r in results))
    if extra_modes:
        out += ["### Variantes", "", *comparative_table(results, modelos, modos=extra_modes), ""]

    for pol, title in (("permisivo", "Política permisiva (cota superior: un hermano con la misma SQL puede aparecer)"),
                       ("estricto", "Política estricta (sin ningún ejemplo de la misma necesidad)")):
        if any(r["politica"] == pol for r in results):
            out += [f"## {title}", "", *comparative_table(results, modelos, pol, modos=("base", "fewshot", "rag", "harness")), ""]

    summ = summarize(results)
    out += ["## Calidad de la SQL y costo (política oficial)", "",
            "| Modelo | Modo | Conjunto | Aciertos | SQL ejecutable | Columnas inventadas | Intentos prom. | p50 (s) | p95 (s) | RAM Ollama (MB) |",
            "|---|---|---|---|---|---|---:|---:|---:|---:|"]
    for s in summ.values():
        if s["politica"] in ("n/a", "sin_gemelas"):
            out.append(f"| {s['modelo']} | {MODO_NOMBRE[s['modo']]} | {s['conjunto']} | {s['aciertos']}/{s['n']} ({s['pct']:.0f} %) "
                       f"| {s['ejecutable_pct']:.0f} % | {s['alucina_columnas_pct']:.0f} % | {s['intentos_prom']} "
                       f"| {s['latencia_p50']} | {s['latencia_p95']} | {s['ram_mb'] or '—'} |")

    out += ["", "## Vistas vs no vistas", "",
            "*Vistas*: preguntas de una necesidad cuyos hermanos están en el catálogo (golden N1-N10 y todo el heldout). "
            "*No vistas*: golden básico y anclada (el catálogo no tiene su tipo) y cualquier ítem bajo la política estricta. "
            "Se muestran las tres políticas de ejemplos: con `permisivo` puede aparecer un hermano con la misma SQL.", "",
            "| Modelo | Modo | Política | Golden negocio (vistas) | Golden básico+anclada (no vistas) | Heldout (vistas) |",
            "|---|---|---|---|---|---|"]
    for model in modelos:
        for modo in ("base", "fewshot", "rag", "harness"):
            for pol in (["n/a"] if modo == "base" else list(POLITICAS)):
                rows = pick(results, modelo=model, modo=modo, politica=pol)
                if not rows:
                    continue
                out.append(f"| {model} | {MODO_NOMBRE[modo]} | {pol} "
                           f"| {cell([r for r in rows if r['conjunto'] == 'golden' and r['tipo'] == 'negocio'])} "
                           f"| {cell([r for r in rows if r['conjunto'] == 'golden' and r['tipo'] in SPLIT_SIN_HERMANOS])} "
                           f"| {cell([r for r in rows if r['conjunto'] == 'negativas_heldout'])} |")

    out += ["", "## Comparación pareada frente a Base (política oficial)", "",
            "Con pocos ítems (24 y 45) una diferencia de uno o dos aciertos es ruido: la prueba de los signos "
            "mira solo los ítems que cambiaron de resultado. p < 0.05 sugiere que el cambio no es azar.", "",
            *paired_table(results, modelos), ""]

    out += ["", "## Heldout por tipo de variante (política oficial)", "",
            "| Modelo | Modo | " + " | ".join(catalogo.TIPOS) + " |", "|---|---|" + "---|" * len(catalogo.TIPOS)]
    for s in summ.values():
        if s["conjunto"] == "negativas_heldout" and s["politica"] in ("n/a", "sin_gemelas"):
            out.append(f"| {s['modelo']} | {MODO_NOMBRE[s['modo']]} | " + " | ".join(s["por_tipo"].get(t, "—") for t in catalogo.TIPOS) + " |")

    out += ["", "## Categorías de falla (política oficial, golden + heldout)", "",
            "| Modelo | Modo | " + " | ".join(ev.FAILURE_CATEGORIES) + " |", "|---|---|" + "---:|" * len(ev.FAILURE_CATEGORIES)]
    for model in modelos:
        for modo in MODOS:
            rows = [r for r in results if r["modelo"] == model and r["modo"] == modo and r["politica"] in ("n/a", "sin_gemelas")]
            if rows:
                out.append(f"| {model} | {MODO_NOMBRE[modo]} | " + " | ".join(
                    str(sum(r["fallo_categoria"] == c for r in rows)) for c in ev.FAILURE_CATEGORIES) + " |")

    out += ["", "## Cambios frente a Base (puntos porcentuales, política oficial)", "",
            "| Modelo | Conjunto | " + " | ".join(MODO_NOMBRE[m] for m in ("fewshot", "rag", "harness")) + " |",
            "|---|---|---|---|---|"]
    for model in modelos:
        for conjunto in CONJUNTOS:
            base = summ.get(f"{model}|base|n/a|{conjunto}")
            if not base:
                continue
            deltas = []
            for modo in ("fewshot", "rag", "harness"):
                s = summ.get(f"{model}|{modo}|sin_gemelas|{conjunto}")
                deltas.append("—" if not s else f"{s['pct'] - base['pct']:+.0f}")
            out.append(f"| {model} | {conjunto} | " + " | ".join(deltas) + " |")
    out += ["", "## Detalle de fallas (primeras de cada celda)", ""]
    shown = set()
    for r in results:
        key = (r["modelo"], r["modo"], r["politica"], r["conjunto"])
        if not r["ok"] and key not in shown and r["politica"] in ("n/a", "sin_gemelas"):
            shown.add(key)
            sql = (r["sql"] or "").replace("\n", " ")[:160]
            out.append(f"- `{r['modelo']}` · {MODO_NOMBRE[r['modo']]} · {r['conjunto']} · {r['id']} · "
                       f"{r['fallo_categoria']}: {str(r['fallo_detalle'])[:110]} — `{sql}`")
    return "\n".join(out) + "\n"


def make_chart(results: list[dict], path: Path, simulado: bool = False) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    modelos = list(dict.fromkeys(r["modelo"] for r in results))
    modos = ("base", "fewshot", "rag", "harness")
    colors = {"base": "#9DB7D5", "fewshot": "#F4A259", "rag": "#3C74A6", "harness": "#D9531E"}
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), sharey=True)
    for ax, (conjunto, titulo) in zip(axes, (("golden", "Golden (24, leave-one-out)"),
                                              ("negativas_heldout", "Heldout (variantes reservadas)"))):
        width = 0.2
        for j, modo in enumerate(modos):
            vals = []
            for model in modelos:
                rows = pick(results, modelo=model, modo=modo, conjunto=conjunto,
                            politica="n/a" if modo == "base" else "sin_gemelas")
                vals.append(100 * sum(r["ok"] for r in rows) / len(rows) if rows else None)
            xs = [i + (j - 1.5) * width for i in range(len(modelos))]
            bars = ax.bar(xs, [v or 0 for v in vals], width, label=MODO_NOMBRE[modo], color=colors[modo])
            for b, v in zip(bars, vals):
                label = "s/d" if v is None else f"{v:.0f}"
                ax.annotate(label, (b.get_x() + b.get_width() / 2, v or 0), ha="center", va="bottom", fontsize=9)
        ax.set_xticks(range(len(modelos)))
        ax.set_xticklabels(modelos, fontsize=10)
        ax.set_title(titulo, fontsize=12)
        ax.set_ylim(0, 112)
        ax.grid(axis="y", alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("% de aciertos (comparador determinista)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", frameon=False, ncol=4, fontsize=11)
    fig.suptitle("Fase 11: Base | Few shot | RAG | Harness (offline, política sin_gemelas)"
                 + ("   — SIMULADO" if simulado else ""), fontsize=13)
    fig.tight_layout(rect=(0, 0.07, 1, 0.95))
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return True


def write_outputs(results: list[dict], meta: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "resultados.json").write_text(json.dumps({"meta": meta, "resultados": results},
                                                         ensure_ascii=False, indent=1), encoding="utf-8")
    cols = ["modelo", "modo", "politica", "conjunto", "tipo", "id", "necesidad", "ok", "motivo", "fuente",
            "ejecutable", "alucina_columnas", "intentos", "acerto_en_intento", "latencia_s", "fallo_categoria",
            "ejemplos", "ram_mb", "sql"]
    with open(out_dir / "resultados.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow({**r, "ejemplos": " ".join(r.get("ejemplos") or []),
                        "sql": (r.get("sql") or "").replace("\n", " ")})
    (out_dir / "tabla_comparativa.md").write_text(build_markdown(results, meta), encoding="utf-8")
    if results:
        make_chart(results, out_dir / "grafica_comparativa.png", meta.get("simulado", False))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=config.BASE_DIR, timeout=5).stdout.strip() or "n/d"
    except Exception:  # noqa: BLE001
        return "n/d"


def file_hash(path: Path) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def build_meta(args, items_by_set, attempts: list | None) -> dict:
    cat = catalogo.load_catalog()
    return {
        "fecha": f"{datetime.now():%Y-%m-%d %H:%M}", "plataforma": f"{platform.platform()} · Python {platform.python_version()}",
        "commit": git_commit(), "red": args.red, "simulado": args.simulado,
        "conexiones_externas": None if attempts is None else len(attempts),
        "catalogo_hash": catalogo.catalog_hash(), "catalogo_n": len(cat),
        "catalogo_train": sum(r["split"] == "train" for r in cat), "catalogo_heldout": sum(r["split"] == "heldout" for r in cat),
        "golden_hash": file_hash(ev.GOLDEN_PATH), "max_intentos": args.max_intentos, "reparacion": args.reparacion,
        "repeticiones": args.repeticiones, "modelos": args.modelos, "modos": args.modos, "politicas": args.politicas,
        "conjuntos": args.conjuntos, "consistencia": args.consistencia, "rag_min_score": config.RAG_MIN_SCORE,
        "fewshot_k": config.FEWSHOT_K, "fewshot_max_chars": config.FEWSHOT_MAX_CHARS,
        "n_items": {k: len(v) for k, v in items_by_set.items()},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Experimento de la fase 11.", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--modelos", nargs="+", default=config.SUPPORTED_MODELS)
    ap.add_argument("--modos", nargs="+", choices=list(MODOS), default=["base", "fewshot", "rag", "harness"])
    ap.add_argument("--conjuntos", nargs="+", choices=list(CONJUNTOS), default=list(CONJUNTOS))
    ap.add_argument("--politicas", nargs="+", choices=list(POLITICAS), default=["sin_gemelas"])
    ap.add_argument("--max-intentos", type=int, default=2)
    ap.add_argument("--reparacion", choices=["produccion", "comparador"], default="produccion")
    ap.add_argument("--repeticiones", type=int, default=1)
    ap.add_argument("--consistencia", type=int, default=1, help="muestras por pregunta en el harness")
    ap.add_argument("--red", choices=["offline", "online"], default="offline")
    ap.add_argument("--salida", type=Path, default=OUT_DIR)
    ap.add_argument("--simulado", action="store_true", help="LLM = SQL de referencia (solo prueba de humo)")
    ap.add_argument("--fresh", action="store_true", help="no reanudar resultados previos de --salida")
    ap.add_argument("--solo-reporte", action="store_true",
                    help="regenera tabla, CSV y gráfica desde --salida/resultados.json sin correr nada")
    args = ap.parse_args(argv)

    if args.solo_reporte:
        data = json.loads((args.salida / "resultados.json").read_text(encoding="utf-8"))
        write_outputs(data["resultados"], data["meta"], args.salida)
        print(f"Reporte regenerado en {args.salida}")
        return 0

    netmode.set_mode(args.red)
    items_by_set = {}
    if "golden" in args.conjuntos:
        items_by_set["golden"] = golden_items()
    if "negativas_heldout" in args.conjuntos:
        items_by_set["negativas_heldout"] = heldout_items()
    all_items = [i for v in items_by_set.values() for i in v]

    if args.simulado:
        llm_factory = lambda _m: oracle_for(all_items)  # noqa: E731
        args.salida = args.salida if args.salida != OUT_DIR else config.BASE_DIR / "eval" / "fase11_simulado"
    else:
        import ollama_manager as om
        if not om.is_server_up() and not om.try_start_server():
            print(f"Ollama no está disponible en {config.OLLAMA_HOST}. Instálalo desde https://ollama.com "
                  "o usa --simulado para una prueba de humo.")
            return 2
        missing = [m for m in args.modelos if not om.is_model_available(m)]
        if missing:
            print(f"Modelos sin descargar: {', '.join(missing)}. Descárgalos con `ollama pull <modelo>`.")
            return 2
        llm_factory = lambda _m: om.chat  # noqa: E731

    out_json = args.salida / "resultados.json"
    previous, done = [], set()
    if out_json.exists() and not args.fresh:
        previous = json.loads(out_json.read_text(encoding="utf-8")).get("resultados", [])
        done = {(r["modelo"], r["modo"], r["politica"], r["conjunto"], r["id"], r.get("repeticion", 0)) for r in previous}
        print(f"Reanudando: {len(previous)} resultados previos.")

    attempts: list = []
    results = list(previous)

    def save(new_results):
        merged = previous + new_results
        write_outputs(merged, build_meta(args, items_by_set, attempts if args.red == "offline" else None), args.salida)

    guard = netmode.block_external_sockets(attempts) if args.red == "offline" else None
    try:
        if guard:
            guard.__enter__()
        new = run_experiment(args.modelos, args.modos, args.conjuntos, args.politicas, args.max_intentos,
                             args.reparacion, args.repeticiones, llm_factory, items_by_set, on_progress=save,
                             done=done, consistencia=args.consistencia)
    finally:
        if guard:
            guard.__exit__(None, None, None)
    results += new
    save(new)
    if not args.simulado:
        import ollama_manager as om
        for m in args.modelos:
            om.unload_model(m)
    print(f"\nResultados en {args.salida} · conexiones externas intentadas: {len(attempts) if args.red == 'offline' else 'n/d (online)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
