"""Prueba del arranque y del chat SIN CONEXIÓN (simulada con un proxy inexistente).

Cómo se simula (no se toca la configuración de red del sistema):
  * Este script y todo lo que lanza reciben HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:9 (nadie
    escucha ahí), NO_PROXY=127.0.0.1,localhost (el tráfico local sigue directo) y un
    PIP_INDEX_URL inalcanzable: pip e internet fallan en el acto.
  * El servidor de Ollama debe estar arrancado con HTTPS_PROXY=http://127.0.0.1:9, así no puede
    llegar al registro de modelos (ver fase5.md §3 para los comandos).

Pasos:
  1. Comprueba que la simulación funciona (internet y pull de Ollama fallan).
  2. ejecutar.bat --no-browser: registra si intentó pip o pull, y el tiempo hasta el health 200.
  3. Con Playwright: espera "● listo" en el Asistente y hace una pregunta verificada (D1) y una con
     LLM (D4); registra tiempos y respuestas.
  4. Fuerza los caminos que sí usan la red: un requirement nuevo (pip debe fallar rápido y el
     arranque seguir) y la descarga en segundo plano de un modelo que no está.
  5. Cierra la app con Ctrl+Break.

Uso:  python tools/prueba_sin_red.py   → escribe demo/prueba_sin_red.json y una captura.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROXY = "http://127.0.0.1:9"
ENV = dict(os.environ, HTTP_PROXY=PROXY, HTTPS_PROXY=PROXY, http_proxy=PROXY, https_proxy=PROXY,
           NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
           PIP_INDEX_URL="http://127.0.0.1:9/simple", PYTHONIOENCODING="utf-8")
FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
report: dict = {}


def http(url: str, data: bytes | None = None, timeout: float = 10.0) -> tuple[int, str]:
    """Petición con los proxies del entorno simulado."""
    handler = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    opener = urllib.request.build_opener(handler)
    if "127.0.0.1" in url:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def log_tail(since: int) -> str:
    text = (ROOT / "logs" / "ejecutar.log").read_text(encoding="utf-8", errors="replace")
    return text[since:]


def log_size() -> int:
    path = ROOT / "logs" / "ejecutar.log"
    return len(path.read_text(encoding="utf-8", errors="replace")) if path.exists() else 0


def main() -> int:
    # 1. La simulación funciona
    t0 = time.perf_counter()
    status, body = http("https://pypi.org/simple/pip/")
    report["internet"] = {"status": status, "detalle": body[:120], "s": round(time.perf_counter() - t0, 2)}
    t0 = time.perf_counter()
    status, body = http("http://127.0.0.1:11434/api/pull",
                        json.dumps({"model": "smollm:135m", "stream": False}).encode(), timeout=60)
    report["ollama_registro"] = {"status": status, "detalle": body[:160],
                                 "s": round(time.perf_counter() - t0, 2)}
    print("simulación:", json.dumps(report, ensure_ascii=False))

    # 2. Arranque normal sin red
    start = log_size()
    t0 = time.perf_counter()
    proc = subprocess.Popen(["cmd", "/c", str(ROOT / "ejecutar.bat"), "--no-browser"], cwd=ROOT,
                            env=ENV, creationflags=FLAGS, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    health, port = None, None
    while time.perf_counter() - t0 < 120:
        found = re.search(r"App lista en http://localhost:(\d+)", log_tail(start))
        if found:
            port = int(found.group(1))
            if http(f"http://127.0.0.1:{port}/_stcore/health", timeout=1)[0] == 200:
                health = round(time.perf_counter() - t0, 1)
                break
        time.sleep(0.5)
    tail = log_tail(start)
    report["puerto"] = port
    report["arranque"] = {
        "health_200_s": health,
        "intento_pip": "pip\" install" in tail or "Instalando dependencias" in tail,
        "intento_pull": "Descargando" in tail and "segundo plano" in tail,
        "precalentamiento": "Precalentando" in tail,
        "log": [ln.split("INFO", 1)[-1].strip() for ln in tail.splitlines()
                if "INFO" in ln and "$ " not in ln and ln.strip()][-12:],
    }
    print("arranque:", json.dumps(report["arranque"], ensure_ascii=False, indent=1))

    # 3. Chat sin red (Playwright, fuera del entorno con proxy)
    from playwright.sync_api import sync_playwright
    chat = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        page.goto(f"http://127.0.0.1:{port}/asistente")
        page.wait_for_selector("[data-testid='stChatInput']", timeout=90_000)
        t0 = time.perf_counter()
        page.wait_for_selector("text=● listo", timeout=180_000)
        chat["listo_tras_s"] = round(time.perf_counter() - t0, 1)
        spec = json.loads((ROOT / "demo" / "preguntas_demo.json").read_text(encoding="utf-8"))
        q = {it["id"]: it["pregunta"] for it in spec["preguntas"]}
        for qid in ("D1", "D4"):
            box = page.get_by_placeholder("Pregunta sobre ventas, inventario, tiendas…")
            n = page.locator(".badge").count()
            t0 = time.perf_counter()
            box.fill(q[qid])
            box.press("Enter")
            page.wait_for_function(f"() => document.querySelectorAll('.badge').length > {n}",
                                   timeout=180_000)
            chat[qid] = {"s": round(time.perf_counter() - t0, 1),
                         "origen": page.locator(".badge").last.inner_text()}
        time.sleep(2)
        page.screenshot(path=str(ROOT / "docs" / "capturas" / "sin_red_chat.png"), full_page=False)
        texts = page.locator("[data-testid='stChatMessage']").all_inner_texts()
        chat["ultima_respuesta"] = " ".join(texts[-1].split())[:300] if texts else ""
        browser.close()
    report["chat"] = chat
    print("chat:", json.dumps(chat, ensure_ascii=False, indent=1))

    # 5 (antes de 4, para liberar el puerto): cierre limpio
    proc.send_signal(signal.CTRL_BREAK_EVENT)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    report["cierre_codigo"] = proc.returncode

    # 4a. Requirement nuevo: pip necesita la red → debe fallar rápido y el arranque seguir
    req = ROOT / "requirements.txt"
    backup = req.read_bytes()
    try:
        req.write_text(req.read_text(encoding="utf-8") + "tabulate>=0.9\n", encoding="utf-8")
        start = log_size()
        t0 = time.perf_counter()
        r = subprocess.run([sys.executable, str(ROOT / "bootstrap.py"), "--smoke", "--no-browser"],
                           cwd=ROOT, env=ENV, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        tail = log_tail(start)
        report["pip_sin_red"] = {"codigo": r.returncode, "s": round(time.perf_counter() - t0, 1),
                                 "aviso": "no se pudieron actualizar" in tail,
                                 "app_arranco": "App lista" in tail}
    finally:
        req.write_bytes(backup)
    print("pip sin red:", report["pip_sin_red"])

    # 4b. Descarga en segundo plano de un modelo que no está
    t0 = time.perf_counter()
    r = subprocess.run([sys.executable, str(ROOT / "bootstrap.py"), "--_pull", "smollm:135m"],
                       cwd=ROOT, env=ENV, capture_output=True, text=True)
    pull_log = ROOT / "logs" / "pull_smollm_135m.log"
    report["pull_sin_red"] = {
        "codigo": r.returncode, "s": round(time.perf_counter() - t0, 1),
        "lock_eliminado": not (ROOT / "logs" / "pull_smollm_135m.lock").exists(),
        "log": pull_log.read_text(encoding="utf-8", errors="replace").strip()[:200]
        if pull_log.exists() else ""}
    print("pull sin red:", report["pull_sin_red"])
    for f in (pull_log,):
        f.unlink(missing_ok=True)

    (ROOT / "demo" / "prueba_sin_red.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
