"""Precalentamiento del modelo por defecto (lo lanza bootstrap.py en segundo plano).

Carga el modelo en RAM con las MISMAS opciones que el chat (num_ctx, keep_alive) y le
envía el system prompt real de generación de SQL con num_predict=1. Así Ollama deja
el modelo cargado y el prefijo del prompt en su caché: la primera pregunta de la demo
no paga ni la carga (~5 s) ni el procesamiento de ~1,500 tokens de system prompt.

Uso:  python warmup.py [modelo]
"""

from __future__ import annotations

import sys
import threading
import time

import config
import ollama_manager as om
import sql_engine as se

_lock = threading.Lock()
_in_progress: set[str] = set()


def start_background(model: str) -> bool:
    """Precalienta en un hilo si no hay ya uno en curso para ese modelo (una vez por proceso).

    La usa el Asistente cuando el modelo está descargado pero no cargado en RAM, para que el
    indicador "◐ cargando…" sea cierto aunque la app se haya abierto sin bootstrap.py.
    Devuelve True si lanzó un hilo nuevo.
    """
    with _lock:
        if model in _in_progress:
            return False
        _in_progress.add(model)

    def run() -> None:
        try:
            warm_up(model)
        except Exception:  # noqa: BLE001 - el indicador seguirá mostrando el estado real
            pass
        finally:
            with _lock:
                _in_progress.discard(model)

    threading.Thread(target=run, name=f"warmup-{model}", daemon=True).start()
    return True


def is_warming(model: str) -> bool:
    with _lock:
        return model in _in_progress


def warm_up(model: str = config.DEFAULT_MODEL) -> float:
    """Devuelve los segundos que tardó. Lanza OllamaError si Ollama no responde."""
    t0 = time.perf_counter()
    messages = [{"role": "system", "content": se.build_system_prompt()},
                {"role": "user", "content": "¿Cuántas tiendas hay?"}]
    om.chat(model, messages, num_predict=1)
    return time.perf_counter() - t0


def main(argv: list[str]) -> int:
    model = argv[1] if len(argv) > 1 else config.DEFAULT_MODEL
    try:
        seconds = warm_up(model)
    except Exception as exc:  # noqa: BLE001 - proceso en segundo plano: se registra y termina
        print(f"precalentamiento fallido: {exc}")
        return 1
    print(f"{model} precalentado en {seconds:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
