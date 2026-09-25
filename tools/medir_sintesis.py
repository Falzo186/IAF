"""Mide la latencia de las respuestas verificadas con y sin síntesis del LLM.

Uso:  python tools/medir_sintesis.py [--model qwen2.5:1.5b]
Usa las 10 preguntas de negocio del golden set (todas se enrutan a SQL verificada).
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import ollama_manager as om  # noqa: E402
import sql_engine as se  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=config.DEFAULT_MODEL)
    args = ap.parse_args()

    items = json.loads((config.BASE_DIR / "eval" / "golden.json").read_text(encoding="utf-8"))["items"]
    questions = [it["pregunta"] for it in items if it["nivel"] == "negocio"]

    om.chat(args.model, [{"role": "user", "content": "hola"}], num_predict=1)  # carga en RAM
    out = {}
    for label, synth in (("con síntesis LLM", True), ("sin síntesis (plantilla)", False)):
        times = []
        for q in questions:
            t0 = time.perf_counter()
            r = se.answer_question(q, args.model, verified_synthesis=synth)
            times.append(time.perf_counter() - t0)
            assert r.source == "verificada" and r.error is None, (q, r.source, r.error)
        out[label] = times
        print(f"{label:<26} p50 {statistics.median(times):6.2f} s   p95 {sorted(times)[-1]:6.2f} s   "
              f"(n={len(times)})")
    print(json.dumps({k: [round(t, 2) for t in v] for k, v in out.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
