"""Valida las preguntas de la demo (demo/preguntas_demo.json) con modelos reales.

Cada repetición es UNA conversación completa D1→D7, con historial como en la app (D5 es
seguimiento de D4). Por pregunta registra: origen, acierto frente a la referencia, latencia
y la respuesta textual. Una pregunta es "apta para demo" si acierta 5/5 con qwen2.5:1.5b.

Uso:
  python tools/validar_demo.py                         # qwen x5 + llama x2 (secuencia completa)
  python tools/validar_demo.py --alternativas demo/alternativas.json
      valida formulaciones alternativas: {"D3": ["frase 1", "frase 2"], ...}
      (para D5 se antepone D4 para que exista el historial)
Resultados: demo/validacion_demo.json (+ _alternativas.json) y demo/validacion_demo.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import db  # noqa: E402
import ollama_manager as om  # noqa: E402
import sql_engine as se  # noqa: E402
import warmup  # noqa: E402
from business_queries import BY_ID, run_business_query  # noqa: E402
from eval_text2sql import compare_results  # noqa: E402

DEMO = config.BASE_DIR / "demo"
DESTRUCTIVE = ("DELETE", "DROP", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "REPLACE INTO")


def db_fingerprint() -> tuple[str, int]:
    digest = hashlib.sha256(config.DB_PATH.read_bytes()).hexdigest()
    customers = int(db.run_query("SELECT COUNT(*) AS n FROM customers")["n"].iloc[0])
    return digest, customers


def reference(item: dict):
    if item.get("business_query"):
        return run_business_query(BY_ID[item["business_query"]], **item.get("filters", {}), limit=500)
    if item.get("referencia"):
        return db.run_query(item["referencia"])
    return None


def evaluate(item: dict, r: se.QueryResult, before, after) -> tuple[bool, str]:
    if item.get("seguridad"):
        executed_write = r.sql is not None and r.error is None and any(
            k in r.sql.upper() for k in DESTRUCTIVE)
        intact = before == after
        ok = intact and not executed_write and bool(r.answer)
        if r.source == "solo_lectura":
            detail = "bloqueada por la guarda de solo lectura (sin LLM ni SQL)"
        elif r.error:
            detail = f"rechazada por el validador ({r.error[:80]})"
        else:
            detail = f"se ejecutó solo lectura: {(r.sql or '')[:80]}"
        why = ("BD intacta; " if intact else "¡BD MODIFICADA!; ") + detail
        return ok, why
    route_ok = item["origen"] in ("cualquiera", r.source)
    if r.error:
        return False, f"error: {r.error[:120]}"
    ok, why = compare_results(reference(item), r.df, item["check"])
    if not route_ok:
        why = f"ruta {r.source} (se esperaba {item['origen']}); " + why
    return ok and route_ok, why


def run_conversation(items: list[dict], model: str) -> list[dict]:
    history, out = [], []
    for item in items:
        before = db_fingerprint() if item.get("seguridad") else None
        t0 = time.perf_counter()
        r = se.answer_question(item["pregunta"], model, history)  # como la app: historial acumulado
        latency = time.perf_counter() - t0
        after = db_fingerprint() if item.get("seguridad") else None
        ok, why = evaluate(item, r, before, after)
        out.append({"id": item["id"], "pregunta": item["pregunta"], "modelo": model, "ok": ok,
                    "motivo": why, "origen": r.source, "intentos": r.attempts,
                    "latencia_s": round(latency, 2), "respuesta": r.answer, "sql": r.sql,
                    "filtros": r.filters, "no_soportados": r.unsupported_filters})
        if r.sql and r.error is None:
            history.append({"question": item["pregunta"], "sql": r.sql})
    return out


def prepare(model: str) -> None:
    for m in om.loaded_models():
        if m != model:
            om.unload_model(m)
    warmup.warm_up(model)  # como en la demo: bootstrap precalienta el modelo por defecto


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=["qwen2.5:1.5b=5", "llama3.2:1b=2"])
    ap.add_argument("--alternativas", type=Path, default=None)
    ap.add_argument("--ids", nargs="+", default=None,
                    help="revalida solo estas preguntas (sin historial previo) y fusiona el resultado")
    args = ap.parse_args()

    spec = json.loads((DEMO / "preguntas_demo.json").read_text(encoding="utf-8"))
    items = spec["preguntas"]
    by_id = {it["id"]: it for it in items}

    sequences = [items if not args.ids else [by_id[i] for i in args.ids]]
    if args.alternativas:
        alts = json.loads(args.alternativas.read_text(encoding="utf-8"))
        sequences = []
        order = [it["id"] for it in items]
        for qid, phrasings in alts.items():
            for phr in phrasings:
                # Una alternativa puede ser solo el texto (misma referencia) o un objeto con su
                # propia "pregunta", "referencia" y "check" (reemplazo con otra pregunta).
                extra = phr if isinstance(phr, dict) else {"pregunta": phr}
                alt = dict(by_id[qid], id=f"{qid}*", origen="cualquiera", **extra)
                # Misma conversación que en la demo: las preguntas previas van antes (historial).
                sequences.append(items[:order.index(qid)] + [alt])

    results = []
    for run in args.runs:
        model, n = run.split("=")
        prepare(model)
        for rep in range(int(n)):
            for seq in sequences:
                for row in run_conversation(seq, model):
                    if args.alternativas and not row["id"].endswith("*"):
                        continue  # preguntas previas: solo aportan el historial
                    row["repeticion"] = rep + 1
                    results.append(row)
                    print(f"[{'OK ' if row['ok'] else 'MAL'}] {model:<14} {row['id']:<4} "
                          f"{row['latencia_s']:6.1f}s {row['origen']:<12} {row['motivo'][:70]}", flush=True)

    suffix = "_alternativas" if args.alternativas else ""
    if args.ids and not args.alternativas:
        previous = json.loads((DEMO / "validacion_demo.json").read_text(encoding="utf-8"))
        results = [r for r in previous if r["id"] not in args.ids] + results
    (DEMO / f"validacion_demo{suffix}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def summarize(rows: list[dict], model: str, qid: str, question: str | None = None) -> dict:
    sel = [r for r in rows if r["modelo"] == model and r["id"] == qid
           and (question is None or r["pregunta"] == question)]
    if not sel:
        return {}
    lat = [r["latencia_s"] for r in sel]
    return {"n": len(sel), "ok": sum(r["ok"] for r in sel), "p50": statistics.median(lat),
            "max": max(lat), "origenes": sorted({r["origen"] for r in sel})}


def _fmt(s: dict) -> tuple[str, str]:
    if not s:
        return "—", "—"
    return f"{s['ok']}/{s['n']}", f"{s['p50']:.1f} / {s['max']:.1f}"


def _clean(text: str, n: int = 260) -> str:
    text = " ".join((text or "").split()).replace("|", "/")
    return text if len(text) <= n else text[: n - 1] + "…"


def write_report(qwen: str = "qwen2.5:1.5b", llama: str = "llama3.2:1b") -> Path:
    """demo/validacion_demo.md a partir de validacion_demo.json (y _alternativas.json si existe)."""
    spec = json.loads((DEMO / "preguntas_demo.json").read_text(encoding="utf-8"))
    rows = json.loads((DEMO / "validacion_demo.json").read_text(encoding="utf-8"))
    alt_path = DEMO / "validacion_demo_alternativas.json"
    alts = json.loads(alt_path.read_text(encoding="utf-8")) if alt_path.exists() else []

    out = ["# Validación de las preguntas de la demo", "",
           "Generado por `python tools/validar_demo.py`. Cada repetición es **una conversación completa**",
           "D1→D7 a través de `sql_engine.answer_question`, con el historial acumulado como en la app",
           "(D5 es seguimiento de D4). Configuración de la app: `VERIFIED_SYNTHESIS = False` (las verificadas",
           "responden con la frase calculada), `KEEP_ALIVE = 60m` y el modelo precalentado como lo deja",
           "`bootstrap.py`. CPU sin GPU. **Apta para demo = 5/5 aciertos con qwen2.5:1.5b.**", "",
           f"| ID | Pregunta | Origen esperado | Origen obtenido (qwen) | qwen aciertos | qwen p50 / máx (s) "
           f"| llama aciertos | llama p50 / máx (s) | ¿Apta? |",
           "|---|---|---|---|---:|---:|---:|---:|---|"]
    for item in spec["preguntas"]:
        q, l = summarize(rows, qwen, item["id"]), summarize(rows, llama, item["id"])
        (qa, ql), (la, ll) = _fmt(q), _fmt(l)
        apt = "**Sí**" if q and q["ok"] == q["n"] == 5 else "No"
        out.append(f"| {item['id']} | {item['pregunta']} | {item['origen']} | {', '.join(q.get('origenes', []))} "
                   f"| {qa} | {ql} | {la} | {ll} | {apt} |")

    if alts:
        out += ["", "## Formulaciones alternativas (para las que no fueron 5/5)", "",
                "| ID | Formulación | Origen (qwen) | qwen aciertos | qwen p50 / máx (s) | llama aciertos | ¿Apta? |",
                "|---|---|---|---:|---:|---:|---|"]
        seen = []
        for r in alts:
            key = (r["id"], r["pregunta"])
            if r["id"].endswith("*") and key not in seen:
                seen.append(key)
        for qid, phr in seen:
            q = summarize(alts, qwen, qid, phr)
            l = summarize(alts, llama, qid, phr)
            (qa, ql), (la, _) = _fmt(q), _fmt(l)
            apt = "**Sí**" if q and q["ok"] == q["n"] == 5 else "No"
            out.append(f"| {qid.rstrip('*')} | {phr} | {', '.join(q.get('origenes', []))} | {qa} | {ql} | {la} | {apt} |")

    replacements = [it for it in spec["preguntas"] if it.get("reemplazo_para_demo")]
    if replacements:
        out += ["", "## Secuencia recomendada para la demo", ""]
        for it in spec["preguntas"]:
            rep = it.get("reemplazo_para_demo")
            if rep:
                out.append(f"- **{it['id']} → reemplazar por:** \"{rep['pregunta']}\" "
                           f"({rep['origen']}; {rep['resultado']}). Motivo: {it['resultado_validacion']}")
            else:
                out.append(f"- **{it['id']}:** \"{it['pregunta']}\"")
    out += ["", "## Respuesta textual (primera repetición de qwen2.5:1.5b)", ""]
    for item in spec["preguntas"]:
        first = next((r for r in rows if r["modelo"] == qwen and r["id"] == item["id"]), None)
        if first:
            out.append(f"- **{item['id']}** ({first['origen']}): {_clean(first['respuesta'])}")
    out += ["", "## Fallos observados", ""]
    fails = [r for r in rows + alts if not r["ok"]]
    if not fails:
        out.append("Ninguno.")
    for r in fails:
        out.append(f"- {r['modelo']} · {r['id']} · rep. {r['repeticion']} · {r['origen']}: {_clean(r['motivo'], 200)}"
                   + (f" — SQL: `{_clean(r['sql'] or '', 160)}`" if r.get("sql") else ""))
    path = DEMO / "validacion_demo.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    if "--reporte" in sys.argv:
        print(write_report())
        sys.exit(0)
    sys.exit(main())
