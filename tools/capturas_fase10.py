"""Capturas de la fase 10: los selectores "Modelo" y "Modelo juez" desplegados (solo 3 modelos).

Uso:  python tools/capturas_fase10.py [--url http://localhost:8501]  → docs/capturas/fase10_*.png
"""

import argparse

from playwright.sync_api import sync_playwright

from capturas import OUT, wait_ready


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        page.goto(args.url.rstrip("/") + "/asistente")
        wait_ready(page, ".st-key-needs button", 10)
        page.get_by_text("Verificar con juez").click()
        wait_ready(page, "[data-testid='stSelectbox']", 2)
        for i, name in enumerate(["modelo", "modelo_juez"]):
            page.locator("[data-testid='stSelectbox']").nth(i).click()
            page.wait_for_selector("[role='listbox'] [role='option']")
            options = page.locator("[role='listbox'] [role='option']").all_inner_texts()
            print(name, options)
            page.screenshot(path=str(OUT / f"fase10_selector_{name}.png"),
                            clip={"x": 0, "y": 0, "width": 1366, "height": 480})
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        browser.close()


if __name__ == "__main__":
    main()
