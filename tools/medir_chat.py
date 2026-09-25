"""Mide la posición del botón "+" frente a st.chat_input (verificación del CSS)."""

from playwright.sync_api import sync_playwright

URL = "http://localhost:8501/asistente"

with sync_playwright() as p:
    browser = p.chromium.launch()
    for w, h in ((1366, 768), (390, 844), (1920, 1080)):
        page = browser.new_page(viewport={"width": w, "height": h})
        page.goto(URL)
        page.wait_for_selector("[data-testid='stChatInput'] textarea", timeout=120_000)
        page.wait_for_timeout(2500)
        chat = page.locator("[data-testid='stChatInput']").bounding_box()
        text = page.locator("[data-testid='stChatInput'] textarea").bounding_box()
        plus = page.locator(".st-key-plus button >> visible=true").first.bounding_box()
        cy, py = chat["y"] + chat["height"] / 2, plus["y"] + plus["height"] / 2
        print(f"{w}x{h}: chat x={chat['x']:.0f} w={chat['width']:.0f} cy={cy:.1f} bottom_gap={h - chat['y'] - chat['height']:.1f} | "
              f"plus x={plus['x']:.0f} cy={py:.1f} | texto x={text['x']:.0f} | dy={py - cy:+.1f}")
        page.close()
    browser.close()
