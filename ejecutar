#!/usr/bin/env bash
# Bike Stores - arranque en un clic (Linux y macOS).
# Busca python3 >= 3.10 y delega todo en bootstrap.py (que crea .venv e instala dependencias).
set -u
cd "$(dirname "$0")" || exit 1

PY=""
for candidate in python3 python3.13 python3.12 python3.11 python3.10 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "No se encontró Python 3.10 o superior."
    echo "  Debian/Ubuntu: sudo apt install python3 python3-venv"
    echo "  macOS:         https://www.python.org/downloads/ o 'brew install python@3.12'"
    exit 1
fi

if ! "$PY" -c 'import venv, ensurepip' 2>/dev/null; then
    echo "Tu Python no incluye venv/ensurepip. En Debian/Ubuntu: sudo apt install python3-venv"
    exit 1
fi

exec "$PY" bootstrap.py "$@"
