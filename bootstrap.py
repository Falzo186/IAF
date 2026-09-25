"""Arranque en un clic de Bike Stores (solo biblioteca estándar: corre antes de instalar nada).

Pasos:
  [1/5] Entorno        crea .venv e instala requirements.txt solo si cambió (hash en .venv/.req_hash)
  [2/5] Base de datos  database_builder.py (idempotente)
  [3/5] Ollama         API arriba / iniciar el binario / ofrecer instalarlo / modo sin IA;
                       descarga DEFAULT_MODEL en segundo plano si falta
  [4/5] Puerto         8501 o el siguiente libre
  [5/5] Aplicación     streamlit run app.py, espera /_stcore/health y abre el navegador

Uso:  python bootstrap.py [--sin-ia] [--reset] [--no-browser] [--smoke]
Lo llaman ejecutar.bat (Windows) y ejecutar / ejecutar.sh (Linux y macOS).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENV_DIR = BASE_DIR / ".venv"
REQUIREMENTS = BASE_DIR / "requirements.txt"
HASH_FILE = VENV_DIR / ".req_hash"
LOGS_DIR = BASE_DIR / "logs"
DEFAULT_PORT = 8501
HEALTH_TIMEOUT_S = 60
OLLAMA_START_TIMEOUT_S = 15
IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

log = logging.getLogger("bootstrap")


class BootstrapError(Exception):
    """Error que detiene el arranque; el mensaje ya está en español."""


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    log.setLevel(logging.INFO)
    log.handlers.clear()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(console)
    try:
        filelog = logging.FileHandler(LOGS_DIR / "ejecutar.log", encoding="utf-8")
        filelog.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        log.addHandler(filelog)
    except OSError:
        pass


def step(n: int, text: str) -> None:
    log.info(f"\n[{n}/5] {text}")


def venv_python(venv_dir: Path = VENV_DIR) -> Path:
    return venv_dir / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def file_hash(path: Path) -> str:
    """Hash del contenido normalizado (sin espacios finales ni diferencias CRLF/LF)."""
    lines = [ln.rstrip() for ln in path.read_text(encoding="utf-8").splitlines()]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def needs_install(requirements: Path = REQUIREMENTS, hash_file: Path = HASH_FILE) -> bool:
    if not hash_file.exists():
        return True
    return hash_file.read_text(encoding="utf-8").strip() != file_hash(requirements)


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """True si algo escucha en el puerto (conexión aceptada) o no se puede enlazar."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        if s.connect_ex((host, port)) == 0:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if not IS_WINDOWS:
            # Un puerto recién cerrado queda en TIME_WAIT; Streamlit lo reutiliza con SO_REUSEADDR,
            # así que la prueba debe hacer lo mismo. (En Windows esa opción permitiría "robar" un
            # puerto en uso, por eso no se aplica allí.)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return True
    return False


def find_free_port(start: int = DEFAULT_PORT, attempts: int = 50) -> int:
    for port in range(start, start + attempts):
        if not port_in_use(port):
            return port
    raise BootstrapError(f"No hay puertos libres entre {start} y {start + attempts - 1}.")


def http_get(url: str, timeout: float = 2.0) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, OSError, ValueError):
        return 0, b""


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    log.info("  $ " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], **kwargs)


# ---------------------------------------------------------------------------
# [1/5] Entorno
# ---------------------------------------------------------------------------

def ensure_venv(reset: bool = False) -> Path:
    if reset and VENV_DIR.exists():
        log.info("  --reset: se borra .venv")
        shutil.rmtree(VENV_DIR)
    py = venv_python()
    if not py.exists():
        log.info("  Creando el entorno virtual .venv (solo la primera vez)…")
        r = run([sys.executable, "-m", "venv", VENV_DIR])
        if r.returncode != 0 or not py.exists():
            raise BootstrapError("No se pudo crear el entorno virtual .venv. ¿Está completo tu Python?")
    if needs_install():
        log.info("  Instalando dependencias (la primera vez tarda unos minutos)…")
        r = run([py, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                 "-r", REQUIREMENTS])
        if r.returncode != 0:
            raise BootstrapError("Falló la instalación de dependencias. Revisa tu conexión a internet "
                                 "y vuelve a intentarlo (o usa --reset).")
        HASH_FILE.write_text(file_hash(REQUIREMENTS), encoding="utf-8")
        log.info("  Dependencias instaladas.")
    else:
        log.info("  Dependencias al día (requirements.txt sin cambios).")
    return py


# ---------------------------------------------------------------------------
# [2/5] Base de datos
# ---------------------------------------------------------------------------

def build_database(py: Path, force: bool = False) -> None:
    cmd = [py, BASE_DIR / "database_builder.py"] + (["--force"] if force else [])
    r = run(cmd, cwd=BASE_DIR)
    if r.returncode != 0:
        raise BootstrapError("No se pudo construir la base de datos (ver el mensaje de arriba). "
                             "Revisa que los 9 CSV estén en data/bike_stores/.")
    log.info("  Base de datos lista.")


# ---------------------------------------------------------------------------
# [3/5] Ollama
# ---------------------------------------------------------------------------

def read_config() -> dict:
    """Lee OLLAMA_HOST y DEFAULT_MODEL de config.py sin importarlo (puede depender del venv)."""
    values = {"OLLAMA_HOST": os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
              "DEFAULT_MODEL": "qwen2.5:1.5b"}
    try:
        import ast
        tree = ast.parse((BASE_DIR / "config.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "DEFAULT_MODEL" and isinstance(node.value, ast.Constant)):
                values["DEFAULT_MODEL"] = node.value.value
    except (OSError, SyntaxError):
        pass
    return values


def ollama_api_up(host: str) -> bool:
    return http_get(host.rstrip("/") + "/api/version", timeout=2)[0] == 200


def ollama_binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    candidates = []
    if IS_WINDOWS:
        candidates.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Ollama.app/Contents/Resources/ollama"))
    else:
        candidates += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]
    return next((str(c) for c in candidates if c.is_file()), None)


def ollama_state(host: str, api_up=ollama_api_up, binary=ollama_binary) -> str:
    """'up' (la API responde) | 'stopped' (instalado, API caída) | 'missing' (no instalado)."""
    if api_up(host):
        return "up"
    return "stopped" if binary() else "missing"


def start_ollama(binary: str, host: str, timeout: float = OLLAMA_START_TIMEOUT_S):
    """Lanza `ollama serve` en segundo plano. Devuelve el proceso si la API quedó arriba."""
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if IS_WINDOWS:
        kwargs["creationflags"] = NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen([binary, "serve"], **kwargs)
    except OSError:
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ollama_api_up(host):
            return proc
        time.sleep(0.5)
    return None


def ask_yes_no(question: str, default: bool = True, input_fn=input) -> bool:
    """Pregunta [S/n]. Sin consola interactiva devuelve False (no instala nada solo)."""
    if not sys.stdin or not sys.stdin.isatty():
        log.info(f"  {question} → sin consola interactiva: no")
        return False
    try:
        answer = input_fn(f"  {question} [{'S/n' if default else 's/N'}] ").strip().lower()
    except EOFError:
        return False
    if not answer:
        return default
    return answer in ("s", "si", "sí", "y", "yes")


def install_ollama() -> bool:
    system = platform.system()
    if system == "Windows":
        if not shutil.which("winget"):
            log.info("  winget no está disponible. Descarga Ollama desde https://ollama.com/download")
            return False
        r = run(["winget", "install", "--id", "Ollama.Ollama", "-e",
                 "--accept-source-agreements", "--accept-package-agreements"])
        return r.returncode == 0
    if system == "Linux":
        r = run(["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"])
        return r.returncode == 0
    log.info("  En macOS descarga Ollama desde https://ollama.com/download y vuelve a ejecutar.")
    return False


def model_available(host: str, model: str) -> bool:
    status, body = http_get(host.rstrip("/") + "/api/tags", timeout=5)
    if status != 200:
        return False
    try:
        names = {m.get("name") or m.get("model") for m in json.loads(body).get("models", [])}
    except (ValueError, AttributeError):
        return False
    return model in names or f"{model}:latest" in names


def pull_in_background(py_for_helper: str, model: str) -> None:
    """Lanza la descarga del modelo sin bloquear el arranque (ver pull_worker)."""
    sys.path.insert(0, str(BASE_DIR))
    import pull_log
    logfile, lock = pull_log.paths(model, LOGS_DIR)
    if lock.exists():
        log.info(f"  Ya hay una descarga de {model} en curso ({lock.name}).")
        return
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL,
              "cwd": BASE_DIR}
    if IS_WINDOWS:
        kwargs["creationflags"] = NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    lock.write_text(str(os.getpid()), encoding="utf-8")
    subprocess.Popen([py_for_helper, str(BASE_DIR / "bootstrap.py"), "--_pull", model], **kwargs)
    log.info(f"  Descargando {model} en segundo plano (~1 GB). Progreso: logs/{logfile.name}. "
             "La app arranca sin esperar.")


def pull_worker(model: str) -> int:
    """Proceso hijo: descarga el modelo por la API de Ollama y registra el progreso."""
    sys.path.insert(0, str(BASE_DIR))
    import pull_log
    host = read_config()["OLLAMA_HOST"]
    LOGS_DIR.mkdir(exist_ok=True)
    logfile, lock = pull_log.paths(model, LOGS_DIR)
    lock.write_text(str(os.getpid()), encoding="utf-8")
    code = 1
    try:
        with open(logfile, "w", encoding="utf-8") as out:
            req = urllib.request.Request(host.rstrip("/") + "/api/pull",
                                         data=json.dumps({"model": model, "stream": True}).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                last = -1.0
                for raw in resp:
                    event = json.loads(raw or b"{}")
                    if "error" in event:
                        out.write(f"error: {event['error']}\t\n")
                        break
                    total, done = event.get("total") or 0, event.get("completed") or 0
                    pct = round(100.0 * done / total, 1) if total else None
                    if pct is None or pct - last >= 1 or pct >= 100:
                        out.write(f"{event.get('status', '')}\t{'' if pct is None else pct}\n")
                        out.flush()
                        if pct is not None:
                            last = pct
                    if event.get("status") == "success":
                        code = 0
    except Exception as exc:  # noqa: BLE001 - se registra y termina
        with open(logfile, "a", encoding="utf-8") as out:
            out.write(f"error: {exc}\t\n")
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    return code


def ensure_ollama(sin_ia: bool, interactive: bool = True) -> tuple[bool, object]:
    """Devuelve (ia_activa, proceso_ollama_iniciado_por_nosotros_o_None)."""
    if sin_ia:
        log.info("  --sin-ia: se omite Ollama. Dashboard y consultas verificadas disponibles.")
        return False, None
    cfg = read_config()
    host, model = cfg["OLLAMA_HOST"], cfg["DEFAULT_MODEL"]
    state = ollama_state(host)
    started = None
    if state == "up":
        log.info(f"  Ollama responde en {host}.")
    elif state == "stopped":
        log.info("  Ollama está instalado pero apagado: iniciándolo…")
        started = start_ollama(ollama_binary(), host)
        if started is None:
            log.info("  No se pudo iniciar Ollama → MODO SIN IA (el dashboard y las consultas "
                     "verificadas funcionan).")
            return False, None
        log.info("  Ollama iniciado.")
    else:
        log.info("  Ollama no está instalado.")
        if interactive and ask_yes_no("¿Instalar Ollama ahora?") and install_ollama():
            binary = ollama_binary()
            if not ollama_api_up(host) and binary:
                started = start_ollama(binary, host)
            if not ollama_api_up(host):
                log.info("  Ollama se instaló pero no responde todavía → MODO SIN IA por ahora.")
                return False, None
            log.info("  Ollama instalado y en ejecución.")
        else:
            log.info("  → MODO SIN IA: el dashboard y las consultas verificadas funcionan; las "
                     "preguntas libres del Asistente necesitan Ollama.")
            return False, None

    if model_available(host, model):
        log.info(f"  Modelo {model} disponible.")
    else:
        pull_in_background(sys.executable, model)
    return True, started


# ---------------------------------------------------------------------------
# [5/5] Aplicación
# ---------------------------------------------------------------------------

def wait_health(port: int, proc: subprocess.Popen, timeout: float = HEALTH_TIMEOUT_S) -> float:
    t0 = time.monotonic()
    url = f"http://127.0.0.1:{port}/_stcore/health"
    while time.monotonic() - t0 < timeout:
        if proc.poll() is not None:
            raise BootstrapError("Streamlit se cerró al arrancar. Revisa logs/streamlit.log.")
        if http_get(url, timeout=1)[0] == 200:
            return time.monotonic() - t0
        time.sleep(0.3)
    raise BootstrapError(f"La app no respondió en {timeout:.0f} s. Revisa logs/streamlit.log.")


def launch_app(py: Path, port: int, ai_enabled: bool) -> subprocess.Popen:
    env = dict(os.environ, BIKESTORES_SIN_IA="0" if ai_enabled else "1", PYTHONIOENCODING="utf-8")
    cmd = [py, "-m", "streamlit", "run", BASE_DIR / "app.py", "--server.headless", "true",
           "--browser.gatherUsageStats", "false", "--server.port", str(port)]
    out = open(LOGS_DIR / "streamlit.log", "w", encoding="utf-8")
    log.info("  $ streamlit run app.py --server.port " + str(port))
    kwargs = {"cwd": BASE_DIR, "env": env, "stdout": out, "stderr": subprocess.STDOUT}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen([str(c) for c in cmd], **kwargs)


def stop_process(proc) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="ejecutar", description="Arranca Bike Stores en un clic.")
    ap.add_argument("--sin-ia", action="store_true", help="no usar Ollama (modo sin IA)")
    ap.add_argument("--reset", action="store_true", help="borra .venv y reconstruye la base de datos")
    ap.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    ap.add_argument("--smoke", action="store_true",
                    help="arranca, comprueba /_stcore/health, cierra y sale con 0 (pruebas)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=argparse.SUPPRESS)
    ap.add_argument("--_pull", metavar="MODELO", help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def _interrupt(*_args) -> None:
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args._pull:
        return pull_worker(args._pull)

    setup_logging()
    if hasattr(signal, "SIGBREAK"):
        # Windows: Ctrl+Break y cerrar la ventana de la consola llegan como SIGBREAK; se tratan
        # como Ctrl+C para que el bloque finally cierre Streamlit limpio.
        signal.signal(signal.SIGBREAK, _interrupt)
    t_start = time.monotonic()
    log.info(f"Bike Stores · arranque ({platform.system()}, Python {platform.python_version()})")
    log.info(f"Carpeta: {BASE_DIR}")
    app = ollama_proc = None
    try:
        step(1, "Entorno de Python")
        py = ensure_venv(reset=args.reset)

        step(2, "Base de datos")
        build_database(py, force=args.reset)

        step(3, "Ollama (IA local)")
        ai_enabled, ollama_proc = ensure_ollama(args.sin_ia, interactive=not args.smoke)

        step(4, "Puerto")
        port = find_free_port(args.port)
        if port != args.port:
            log.info(f"  El puerto {args.port} está ocupado; se usa {port}.")
        else:
            log.info(f"  Puerto {port} libre.")

        step(5, "Aplicación")
        app = launch_app(py, port, ai_enabled)
        waited = wait_health(port, app)
        url = f"http://localhost:{port}"
        total = time.monotonic() - t_start
        log.info(f"  App lista en {url} (health 200 tras {waited:.1f} s; arranque total {total:.1f} s)."
                 + ("" if ai_enabled else "  [MODO SIN IA]"))

        if args.smoke:
            log.info("  --smoke: comprobación correcta; se cierra la app.")
            return 0
        if not args.no_browser:
            webbrowser.open(url)
        log.info("\nPara salir, cierra esta ventana o pulsa Ctrl+C.")
        # Espera con pausas cortas: en Windows, un wait() bloqueante no atiende Ctrl+C/Ctrl+Break.
        while app.poll() is None:
            time.sleep(0.5)
        return 0 if app.returncode == 0 else 1
    except KeyboardInterrupt:
        log.info("\nCerrando la app…")
        return 0
    except BootstrapError as exc:
        log.error(f"\nERROR: {exc}")
        return 1
    finally:
        stop_process(app)
        # Solo se detiene un Ollama que arrancamos nosotros; uno que ya corría se respeta.
        stop_process(ollama_proc)


if __name__ == "__main__":
    sys.exit(main())
