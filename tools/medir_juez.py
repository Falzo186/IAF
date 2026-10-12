"""Latencia del modo "Verificar con juez" con el modelo real (Ollama), sobre necesidades canónicas.

Uso:  python tools/medir_juez.py [--modelo qwen2.5:1.5b] [--necesidades N3 N5 N8]
Escribe docs/medicion_juez.json. Mide answer_with_judge (sin síntesis) y, aparte, la ruta
verificada de siempre para comparar. También registra los tokens reales del prompt del juez.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

import config  # noqa: E402
import judge  # noqa: E402
import ollama_manager as om  # noqa: E402
import sql_engine as se  # noqa: E402
from business_queries import BY_ID  # noqa: E402


def judge_prompt_tokens(model: str, need: str) -> int:
    """Tokens reales (prompt_eval_count de Ollama) del prompt del juez para una necesidad."""
    messages = [{"role": "system", "content": judge.CRITIC_SYSTEM.format(ejemplos=judge.needs_context(need))},
                {"role": "user", "content": "Pregunta: x\n\nSQL generada:\nSELECT 1\n\nResultado:\n(0 filas)"}]
    resp = om.get_client().chat(model=model, messages=messages, keep_alive=config.KEEP_ALIVE,
                                options={"temperature": 0, "num_predict": 1, "num_ctx": 4096})
    return resp.prompt_eval_count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", default=config.DEFAULT_MODEL)
    ap.add_argument("--necesidades", nargs="+", default=["N3", "N5", "N8"])
    args = ap.parse_args()
    if args.modelo not in config.SUPPORTED_MODELS:
        raise SystemExit(f"Modelo no soportado: {args.modelo}")
    questions = yaml.safe_load((ROOT / "reference_answers.yaml").read_text(encoding="utf-8"))
    se.answer_question("¿Cuántos clientes hay?", args.modelo, use_router=False, synthesize_answer=False)  # calienta
    rows = []
    for need in args.necesidades:
        q = questions[need]["pregunta"]
        t0 = time.perf_counter()
        fast = se.answer_question(q, args.modelo, synthesize_answer=False)
        t_fast = time.perf_counter() - t0
        t0 = time.perf_counter()
        r = se.answer_with_judge(q, args.modelo, referencia=se.reference_for(BY_ID[need]), max_intentos=3)
        total = time.perf_counter() - t0
        row = {"necesidad": need, "pregunta": q, "ruta_normal": fast.source, "ruta_normal_s": round(t_fast, 3),
               "juez_total_s": round(total, 1), "intentos": len(r.intentos),
               "coincide": r.reference_match, "tiempo_sql_s": round(r.timings["sql_gen"], 1),
               "tiempo_juez_s": round(r.timings["judge"], 1),
               "detalle": [{k: i[k] for k in ("numero", "exito", "tiempo_segundos", "diagnostico")}
                           for i in r.intentos],
               "tokens_prompt_juez": judge_prompt_tokens(args.modelo, need)}
        rows.append(row)
        print(f"{need}: {total:.1f} s · {len(r.intentos)} intentos · coincide={r.reference_match} · "
              f"juez {row['tiempo_juez_s']} s · prompt juez {row['tokens_prompt_juez']} tokens "
              f"(ruta normal {t_fast:.3f} s, {fast.source})", flush=True)
    out = ROOT / "docs" / "medicion_juez.json"
    out.write_text(json.dumps({"modelo": args.modelo, "resultados": rows}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
