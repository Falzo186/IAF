"""Graba el video de respaldo de la demo con Playwright (1366×768).

Recorrido (~3 min): dashboard (KPIs, desplazamiento por las 4 secciones, "Ver datos" de N6),
Asistente con D1, D2, D3 y D7, clic en "+" (toast "Próximamente") y cambio de modelo a
llama3.2:1b. Requiere la app corriendo (ejecutar.bat o streamlit run app.py).

Uso:  python tools/grabar_demo.py [--url http://localhost:8501]
Salida: demo/respaldo_demo.webm (y .mp4 si hay ffmpeg).
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
W, H = 1366, 768


def pause(s: float) -> None:
    time.sleep(s)


def wait_idle(page, timeout=240):
    """Espera a que Streamlit termine de ejecutar (sin esqueletos ni estado 'running')."""
    deadline = time.time() + timeout
    time.sleep(1)
    while time.time() < deadline:
        busy = page.evaluate("""() => !!document.querySelector('[data-testid="stSkeleton"]')
            || [...document.querySelectorAll('[data-testid="stStatusWidget"], [data-testid="stSpinner"]')]
               .some(e => e.offsetParent !== null)""")
        if not busy:
            return
        time.sleep(0.5)


def scroll_main(page, y: int, steps: int = 12, per_step: float = 0.12) -> None:
    """Desplaza el contenedor principal de Streamlit de forma suave (legible en video)."""
    start = page.evaluate("() => (document.querySelector('[data-testid=\"stMain\"]') || document.scrollingElement).scrollTop")
    for i in range(1, steps + 1):
        pos = start + (y - start) * i / steps
        page.evaluate(f"() => (document.querySelector('[data-testid=\"stMain\"]') || document.scrollingElement).scrollTo(0, {pos})")
        time.sleep(per_step)


def ask(page, text: str, answer_timeout: int = 180) -> None:
    box = page.get_by_placeholder("Pregunta sobre ventas, inventario, tiendas…")
    box.click()
    box.type(text, delay=35)          # que se lea mientras se escribe
    pause(0.6)
    box.press("Enter")
    n_before = page.locator(".badge").count()
    page.wait_for_function(f"() => document.querySelectorAll('.badge').length > {n_before}",
                           timeout=answer_timeout * 1000)
    wait_idle(page)
    scroll_main(page, 100000, steps=8)
    pause(8.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    args = ap.parse_args()
    spec = json.loads((DEMO / "preguntas_demo.json").read_text(encoding="utf-8"))
    # Si la validación recomendó reemplazar una pregunta (D3), el video usa el reemplazo.
    q = {it["id"]: (it.get("reemplazo_para_demo") or {}).get("pregunta", it["pregunta"])
         for it in spec["preguntas"]}

    tmp = DEMO / "_video_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp),
                                  record_video_size={"width": W, "height": H})
        page = ctx.new_page()

        # 1. Dashboard
        page.goto(args.url)
        page.wait_for_function("() => document.querySelectorAll('.js-plotly-plot').length >= 11",
                               timeout=120_000)
        wait_idle(page)
        pause(8)                                   # KPIs y tendencia
        for section in ("Rentabilidad", "Operación e inventario", "Personal", "Riesgo"):
            y = page.evaluate(f"""() => {{
                const el = [...document.querySelectorAll('.section-title')].find(e => e.textContent.includes('{section}'));
                const main = document.querySelector('[data-testid="stMain"]') || document.scrollingElement;
                return el ? el.getBoundingClientRect().top + main.scrollTop - 70 : 0; }}""")
            scroll_main(page, y)
            pause(7)
        # "Ver datos" de N6 (Inventario inactivo)
        # Orden de las tarjetas: N1, N4, N7, N8 · N2, N5, N6, N9 · N3 · N10 → N6 es la 7.ª
        page.get_by_text("Inventario inactivo", exact=True).scroll_into_view_if_needed()
        pause(2)
        expander = page.get_by_text("Ver datos", exact=True).nth(6)
        expander.scroll_into_view_if_needed()
        expander.click()
        page.wait_for_selector("text=Estado inventario", state="attached", timeout=15_000)  # tabla de N6
        pause(8)

        # 2. Asistente
        page.get_by_role("link", name="Asistente").click()
        page.wait_for_selector("[data-testid='stChatInput']", timeout=60_000)
        wait_idle(page)
        pause(3)
        for qid in ("D1", "D2", "D3", "D7"):
            ask(page, q[qid])
        # 3. Botón "+" y cambio de modelo
        page.locator(".st-key-plus button").first.click()
        pause(4)
        wait_idle(page)                       # el clic en "+" provoca un rerun
        scroll_main(page, 0, steps=8)
        pause(1)
        page.locator("[data-testid='stSelectbox']").first.click()   # selector "Modelo"
        pause(1.2)
        if not page.locator("[role='option']").count():
            page.keyboard.press("ArrowDown")  # si el clic solo dio foco, abre la lista
            pause(1)
        page.locator("[role='option']", has_text="llama3.2:1b").first.click()
        page.wait_for_selector("text=llama3.2:1b activo", timeout=60_000)  # toast de cambio
        wait_idle(page)
        pause(8)

        video_path = page.video.path()
        ctx.close()
        browser.close()

    out = DEMO / "respaldo_demo.webm"
    shutil.move(video_path, out)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"video: {out} ({out.stat().st_size / 1e6:.1f} MB, {time.time() - t0:.0f} s de grabación)")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        mp4 = out.with_suffix(".mp4")
        subprocess.run([ffmpeg, "-y", "-i", str(out), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(mp4)], check=True, capture_output=True)
        print(f"mp4: {mp4}")
    else:
        print("ffmpeg no está disponible: solo se generó el .webm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
