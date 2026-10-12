"""Capturas de la fase 9: accesos directos y expander de intentos (1366 px y 390 px).

Uso:  python tools/capturas_fase9.py [--url http://localhost:8501] [--sin-juez]
Requiere la app corriendo y, para el caso de 2+ intentos, Ollama. Guarda PNG en docs/capturas/.
"""

import argparse

from playwright.sync_api import sync_playwright

from capturas import VIEWPORTS, shot, wait_ready, OUT


def element_shot(page, selector, name):
    OUT.mkdir(parents=True, exist_ok=True)
    page.locator(selector).first.screenshot(path=str(OUT / f"{name}.png"))
    print("captura:", f"{name}.png")


def ask_need(page, need, timeout=900):
    before = page.locator(".badge").count()
    page.locator(f".st-key-need_{need} button >> visible=true").first.click()
    wait_ready(page, ".badge", before + 1, timeout=timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    ap.add_argument("--necesidad", default="N8")
    ap.add_argument("--sin-juez", action="store_true", help="omite el caso de 2+ intentos (necesita Ollama)")
    args = ap.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vp, (w, h) in VIEWPORTS.items():
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
            page = ctx.new_page()
            page.goto(args.url.rstrip("/") + "/asistente")
            wait_ready(page, ".st-key-needs button", 10)
            shot(page, f"fase9_asistente_{vp}")
            element_shot(page, ".st-key-needs", f"fase9_botones_{vp}")

            ask_need(page, args.necesidad)                     # ruta verificada: 1 intento
            shot(page, f"fase9_intentos_1_{vp}", full=True)

            if not args.sin_juez and vp == "desktop":
                page.get_by_text("Verificar con juez").click()
                wait_ready(page, "[data-testid='stSelectbox']", 2)
                ask_need(page, args.necesidad)
                wait_ready(page)
                page.locator("[data-testid='stExpander'] summary", has_text="Intentos (").last.click()
                page.get_by_text("Intento 2", exact=False).first.wait_for(state="visible", timeout=30000)
                wait_ready(page)
                shot(page, f"fase9_intentos_varios_{vp}", full=True)
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
