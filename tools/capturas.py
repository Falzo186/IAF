"""Capturas de la app con Playwright (requiere la app corriendo: streamlit run app.py).

Uso:  python tools/capturas.py [--url http://localhost:8501] [--chat "pregunta"]
Guarda PNG en docs/capturas/.
"""

import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "capturas"
VIEWPORTS = {"desktop": (1366, 768), "movil": (390, 844)}


def wait_ready(page, selector=None, count=1, timeout=180):
    """Espera a que Streamlit termine de ejecutar y aparezca el contenido esperado."""
    page.wait_for_selector("[data-testid='stApp']", timeout=timeout * 1000)
    if selector:
        page.wait_for_function(
            "([s, n]) => document.querySelectorAll(s).length >= n", arg=[selector, count],
            timeout=timeout * 1000)
    page.wait_for_function(
        '() => !document.querySelector(\'[data-testid="stSkeleton"]\')', timeout=timeout * 1000)
    time.sleep(2.5)  # animación y dibujo final de los gráficos Plotly


SCROLL_HEIGHT_JS = """() => Math.max(...['[data-testid="stMain"]', '[data-testid="stAppViewContainer"]',
    '[data-testid="stAppScrollToBottomContainer"]', 'section.main']
    .map(s => document.querySelector(s)).filter(Boolean).map(e => e.scrollHeight),
    document.documentElement.scrollHeight)"""


def shot(page, name, full=False):
    """Captura el viewport; con full=True agranda el viewport al alto del contenido
    (Streamlit desplaza un contenedor interno, así que full_page no basta)."""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.png"
    if full:
        size = page.viewport_size
        height = min(int(page.evaluate(SCROLL_HEIGHT_JS)) + 40, 12000)
        page.set_viewport_size({"width": size["width"], "height": height})
        time.sleep(3)  # los gráficos se redibujan con el nuevo tamaño
        page.screenshot(path=str(path))
        page.set_viewport_size(size)
        time.sleep(1)
    else:
        page.screenshot(path=str(path))
    print("captura:", path.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    ap.add_argument("--chat", default="Pedidos entregados tarde por sucursal")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vp, (w, h) in VIEWPORTS.items():
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
            page = ctx.new_page()
            page.goto(args.url)
            wait_ready(page, ".js-plotly-plot", 11)
            shot(page, f"dashboard_{vp}")
            shot(page, f"dashboard_{vp}_completo", full=True)

            page.goto(args.url.rstrip("/") + "/asistente")
            wait_ready(page, "[data-testid='stChatInput']")
            shot(page, f"asistente_{vp}")

            if args.chat:
                box = page.get_by_placeholder("Pregunta sobre ventas, inventario, tiendas…")
                box.fill(args.chat)
                box.press("Enter")
                wait_ready(page, ".badge", 1, timeout=300)
                shot(page, f"asistente_{vp}_respuesta")
                shot(page, f"asistente_{vp}_respuesta_completo", full=True)
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
