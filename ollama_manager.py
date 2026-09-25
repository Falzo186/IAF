"""Gestión del servidor y los modelos locales de Ollama.

Independiente de cualquier UI (no importa Streamlit). Todos los errores de
conexión se traducen a ``OllamaUnavailable`` con un mensaje en español.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import httpx
import ollama

import config

REQUEST_TIMEOUT_S = 120      # generación con modelos pequeños en CPU
PING_TIMEOUT_S = 2
START_TIMEOUT_S = 15


class OllamaError(Exception):
    """Error de Ollama con mensaje en español apto para mostrar al usuario."""


class OllamaUnavailable(OllamaError):
    """El servidor de Ollama no está disponible o no respondió a tiempo."""


class ModelNotFound(OllamaError):
    """El modelo no existe en el registro o no está descargado."""


@lru_cache(maxsize=1)
def get_client() -> ollama.Client:
    """Único cliente de Ollama del proceso (singleton)."""
    return ollama.Client(host=config.OLLAMA_HOST, timeout=REQUEST_TIMEOUT_S)


def _unavailable(exc: Exception) -> OllamaUnavailable:
    return OllamaUnavailable(
        f"No se pudo conectar con Ollama en {config.OLLAMA_HOST}. "
        f"Verifica que esté instalado y en ejecución (`ollama serve`). Detalle: {exc}"
    )


def _is_not_found(exc: ollama.ResponseError) -> bool:
    msg = str(exc.error).lower()
    return exc.status_code == 404 or "not found" in msg or "file does not exist" in msg


# --- Servidor ----------------------------------------------------------------

def is_server_up() -> bool:
    """True si la API responde en ~2 s. Nunca lanza excepción."""
    try:
        r = httpx.get(f"{config.OLLAMA_HOST.rstrip('/')}/api/version", timeout=PING_TIMEOUT_S)
        return r.status_code == 200
    except Exception:
        return False


def find_binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    if sys.platform == "win32":
        default = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if default.is_file():
            return str(default)
    return None


def try_start_server() -> bool:
    """Lanza `ollama serve` en segundo plano si hace falta. True si la API queda disponible."""
    if is_server_up():
        return True
    binary = find_binary()
    if binary is None:
        return False
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                    "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([binary, "serve"], **kwargs)
    except OSError:
        return False
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if is_server_up():
            return True
        time.sleep(0.5)
    return False


# --- Modelos -----------------------------------------------------------------

def list_local_models() -> list[str]:
    try:
        resp = get_client().list()
    except (ConnectionError, httpx.HTTPError) as exc:
        raise _unavailable(exc) from exc
    return sorted(m.model for m in resp.models if m.model)


def is_model_available(name: str) -> bool:
    models = list_local_models()
    candidates = {name} if ":" in name else {name, f"{name}:latest"}
    return any(m in candidates for m in models)


def pull_model(name: str) -> Iterator[dict]:
    """Descarga un modelo. Emite dicts {status, completed, total, percent} para una barra de progreso."""
    try:
        for chunk in get_client().pull(name, stream=True):
            total = chunk.total or 0
            completed = chunk.completed or 0
            yield {
                "status": chunk.status or "",
                "completed": completed,
                "total": total,
                "percent": round(100.0 * completed / total, 1) if total else None,
            }
    except ollama.ResponseError as exc:
        if _is_not_found(exc):
            raise ModelNotFound(f"El modelo '{name}' no existe en el registro de Ollama. Revisa el nombre.") from exc
        msg = str(exc.error).lower()
        if any(k in msg for k in ("dial tcp", "no such host", "lookup", "network", "timeout", "connection")):
            raise OllamaError(
                f"No se pudo descargar '{name}': Ollama no tiene acceso a internet. Detalle: {exc.error}"
            ) from exc
        raise OllamaError(f"Error al descargar '{name}': {exc.error}") from exc
    except (ConnectionError, httpx.HTTPError) as exc:
        raise _unavailable(exc) from exc


def unload_model(name: str) -> None:
    """Libera la RAM del modelo (generate con keep_alive=0). Se usa al cambiar de modelo."""
    try:
        get_client().generate(model=name, prompt="", keep_alive=0)
    except ollama.ResponseError as exc:
        if _is_not_found(exc):
            return  # no estaba cargado ni descargado: nada que liberar
        raise OllamaError(f"No se pudo descargar de memoria '{name}': {exc.error}") from exc
    except (ConnectionError, httpx.HTTPError) as exc:
        raise _unavailable(exc) from exc


def chat(model: str, messages: list[dict], *, temperature: float = 0.0,
         num_ctx: int = 4096, num_predict: int = 400) -> str:
    """Envía una conversación al modelo y devuelve el texto de la respuesta."""
    try:
        resp = get_client().chat(
            model=model,
            messages=messages,
            options={"temperature": temperature, "num_ctx": num_ctx, "num_predict": num_predict},
        )
    except ollama.ResponseError as exc:
        if _is_not_found(exc):
            raise ModelNotFound(
                f"El modelo '{model}' no está descargado. Descárgalo con `ollama pull {model}`."
            ) from exc
        raise OllamaError(f"Ollama devolvió un error con '{model}': {exc.error}") from exc
    except (ConnectionError, httpx.HTTPError) as exc:
        raise _unavailable(exc) from exc
    return resp.message.content or ""
