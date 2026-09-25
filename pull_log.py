"""Estado de las descargas de modelos en segundo plano (solo biblioteca estándar).

bootstrap.py lanza la descarga con `python bootstrap.py --_pull <modelo>`, que escribe
logs/pull_<modelo>.log (una línea por evento: "estado<TAB>porcentaje") y mantiene
logs/pull_<modelo>.lock mientras dura. La app lee estos archivos para mostrar
"↓ descargando… NN %".
"""

from __future__ import annotations

import re
from pathlib import Path


def file_stem(model: str) -> str:
    """Nombre de archivo seguro para un modelo: 'qwen2.5:1.5b' -> 'pull_qwen2.5_1.5b'."""
    return "pull_" + re.sub(r"[^A-Za-z0-9._-]+", "_", model)


def paths(model: str, logs_dir: Path) -> tuple[Path, Path]:
    stem = file_stem(model)
    return Path(logs_dir) / f"{stem}.log", Path(logs_dir) / f"{stem}.lock"


def progress(model: str, logs_dir: Path) -> float | None:
    """Porcentaje de la descarga en curso, o None si no hay ninguna (no existe el .lock).

    Devuelve 0.0 si la descarga empezó pero aún no reporta porcentaje.
    """
    log, lock = paths(model, logs_dir)
    if not lock.exists():
        return None
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0.0
    for line in reversed(lines):
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip():
            try:
                return float(parts[1])
            except ValueError:
                continue
    return 0.0
