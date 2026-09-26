"""Renderiza avance/consola.txt (salida real de avance_json.py) como imagen de terminal.

Uso:  python tools/captura_consola.py  → avance/consola.png
"""

from html import escape
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PROMPT = r"PS C:\Users\alexp\IAF&gt; "

text = (ROOT / "avance" / "consola.txt").read_text(encoding="utf-8")
html = (
    '<html><body style="margin:0;background:#0c0c0c">'
    '<div style="background:#1f1f1f;color:#ccc;font:13px Segoe UI;padding:6px 12px">'
    r"Windows PowerShell — C:\Users\alexp\IAF</div>"
    '<pre style="margin:0;padding:14px 16px;color:#cccccc;font:13px/1.35 Consolas,monospace;'
    'white-space:pre-wrap;width:1100px">'
    f"{PROMPT}python avance_json.py\n{escape(text)}{PROMPT}</pre></body></html>"
)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1140, "height": 600})
    page.set_content(html)
    page.screenshot(path=str(ROOT / "avance" / "consola.png"), full_page=True)
    browser.close()
print("avance/consola.png")
