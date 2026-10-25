"""Generador por plantilla (sin red, sin LLM): variantes de filtro y de ruido por construcción.

Para cada necesidad N1..N10 combina una frase base con tienda / año / rango de fechas de valores
reales de la BD. La SQL sale de business_queries.render_sql (misma SQL verificada con esos filtros),
así que es correcta por construcción y, aun así, pasa por el validador como cualquier otra entrada.
"""

from __future__ import annotations

import unicodedata

import config
import db

# Frase base por necesidad (sin signos de pregunta; distinta de las del golden set).
FRASES = {
    "N1": "cuánto ingreso cedemos en descuentos por producto",
    "N2": "qué productos populares tienen poco stock",
    "N3": "quién lidera las ventas de bicicletas eléctricas",
    "N4": "en qué ciudades se compra con el menor descuento",
    "N5": "cuánto cuestan los envíos tardíos por tienda",
    "N6": "qué inventario lleva tiempo sin moverse",
    "N7": "qué clientes combinan varias marcas en una orden",
    "N8": "cuál es el ticket promedio por tienda",
    "N9": "qué categorías y marcas rotan más lento",
    "N10": "cuánto dinero perdimos por órdenes rechazadas",
}
ABREVIATURAS = {"tienda": "tda", "cuánto": "cuanto", "qué": "q", "cuál": "cual", "órdenes": "ordenes",
                "dinero": "$", "por": "x", "cada": "c/", "clientes": "clientes"}


def ensuciar(texto: str) -> str:
    """Ruido determinista: sin acentos ni signos, abreviaturas y una letra cambiada de lugar."""
    palabras = []
    for w in texto.lower().replace("¿", "").replace("?", "").split():
        palabras.append(ABREVIATURAS.get(w, w))
    texto = " ".join(palabras)
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    largas = sorted(set(w for w in texto.split() if len(w) >= 7), key=lambda w: (-len(w), w))
    if largas:   # intercambia las dos letras centrales de la palabra más larga (un "typo" típico)
        w = largas[0]
        i = len(w) // 2
        texto = texto.replace(w, w[:i - 1] + w[i] + w[i - 1] + w[i + 1:], 1)
    return texto


def _valores(db_path=config.DB_PATH) -> tuple[list[str], list[int]]:
    conn = db.ro_connect(db_path)
    try:
        tiendas = [r[0] for r in conn.execute("SELECT store_name FROM stores ORDER BY store_name")]
        anios = sorted({int(r[0]) for r in conn.execute(
            "SELECT DISTINCT strftime('%Y', order_date) FROM orders")})
    finally:
        conn.close()
    return tiendas, anios


def generar(db_path=config.DB_PATH) -> list[dict]:
    tiendas, anios = _valores(db_path)
    items: list[dict] = []
    for i, (need, frase) in enumerate(FRASES.items()):
        t = [tiendas[(i + k) % len(tiendas)] for k in range(3)]
        y = [anios[(i + k) % len(anios)] for k in range(3)]
        combos = [
            (f"en {t[0]}", {"store_name": t[0]}),
            (f"en {y[0]}", {"date_from": f"{y[0]}-01-01", "date_to": f"{y[0]}-12-31"}),
            (f"en {t[1]} durante {y[1]}", {"store_name": t[1], "date_from": f"{y[1]}-01-01",
                                            "date_to": f"{y[1]}-12-31"}),
            (f"entre {anios[0]} y {anios[1]}", {"date_from": f"{anios[0]}-01-01",
                                                  "date_to": f"{anios[1]}-12-31"}),
        ]
        for n, (sufijo, filtros) in enumerate(combos):
            items.append({"necesidad_base": need, "tipo": "filtro_distinto",
                          "pregunta": f"¿{frase[0].upper() + frase[1:]} {sufijo}?",
                          "sql_desde": {"base": need, **filtros},
                          "notas": f"Plantilla: filtros {filtros}"})
        sufijo, filtros = combos[2]
        items.append({"necesidad_base": need, "tipo": "ruido", "comparador_esperado": "distinta",
                      "pregunta": ensuciar(f"{frase} {sufijo}"),
                      "sql_desde": {"base": need, **filtros},
                      "notas": "Plantilla: ruido (sin acentos, abreviaturas, una letra cambiada) + filtros"})
    return items
