"""Mide la primera respuesta con LLM después del arranque (precalentamiento y keep_alive).

Escenarios:
  frio          el modelo no está en RAM (arranque sin precalentar): se descarga antes de medir
  precalentado  se descarga, se hace la petición de precalentamiento de bootstrap.py y se mide
  inactivo N    se precalienta, se espera N segundos sin usar el modelo y se mide
                (con el keep_alive por defecto de Ollama, 5 min, el modelo se descarga solo)

Uso:  python tools/medir_primera_respuesta.py frio|precalentado|inactivo [--espera 360]
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import ollama_manager as om  # noqa: E402
import sql_engine as se  # noqa: E402

QUESTION = "¿Cuáles son las 5 marcas con más ingreso neto en 2017?"   # ruta LLM (D4)


def loaded_models() -> list[str]:
    with urllib.request.urlopen(config.OLLAMA_HOST + "/api/ps", timeout=5) as r:
        return [m["name"] for m in json.load(r).get("models", [])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("escenario", choices=["frio", "precalentado", "inactivo"])
    ap.add_argument("--espera", type=int, default=360)
    ap.add_argument("--model", default=config.DEFAULT_MODEL)
    ap.add_argument("--minimo", action="store_true", help="precalentar con una petición mínima")
    ap.add_argument("--keep-alive", default=None, help="sobrescribe config.KEEP_ALIVE (p. ej. 5m)")
    args = ap.parse_args()
    if args.keep_alive:
        config.KEEP_ALIVE = args.keep_alive

    for m in loaded_models():
        om.unload_model(m)
    time.sleep(1)
    out = {"escenario": args.escenario, "keep_alive": config.KEEP_ALIVE,
           "cargados_al_inicio": loaded_models()}

    if args.escenario in ("precalentado", "inactivo"):
        t0 = time.perf_counter()
        if args.minimo:  # petición mínima (sin system prompt ni num_ctx del chat): la línea base
            om.get_client().chat(model=args.model, messages=[{"role": "user", "content": "ok"}],
                                 options={"num_predict": 1})
        else:
            import warmup
            warmup.warm_up(args.model)
        out["precalentamiento_s"] = round(time.perf_counter() - t0, 2)
    if args.escenario == "inactivo":
        time.sleep(args.espera)
        out["espera_s"] = args.espera

    out["cargados_antes_de_preguntar"] = loaded_models()
    t0 = time.perf_counter()
    r = se.answer_question(QUESTION, args.model)
    out["primera_respuesta_s"] = round(time.perf_counter() - t0, 2)
    out["ok"] = r.error is None
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
