"""Genera demo/cifras_clave.md: acierto por modelo × modo × nivel, latencias por ruta y las
cifras de negocio más fuertes (calculadas en vivo con la misma SQL verificada del dashboard).

Uso:  python tools/cifras_clave.py
"""

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analytics  # noqa: E402
import config  # noqa: E402

MODELS = ["qwen2.5:1.5b", "llama3.2:1b", "deepseek-r1:1.5b"]
MODES = {"llm": "solo LLM", "full": "sistema completo"}
LEVELS = [("basico", "Básico"), ("negocio", "Negocio"), ("anclada", "Anclada")]


def money(x: float) -> str:
    return f"${x:,.2f}"


def main() -> int:
    results = json.loads((config.BASE_DIR / "eval" / "resultados.json").read_text(encoding="utf-8"))
    out = ["# Cifras clave para la presentación", "",
           "Generado con `python tools/cifras_clave.py` a partir de `eval/resultados.json` y de la",
           "base de datos (misma SQL verificada que el dashboard). CPU sin GPU, Ollama 0.34.4.", "",
           "## 1. Acierto por modelo × modo × nivel", "",
           "| Modelo | Modo | Básico (10) | Negocio (10) | Anclada (4) |", "|---|---|---:|---:|---:|"]
    for m in MODELS:
        for mode, label in MODES.items():
            cells = []
            for lvl, _ in LEVELS:
                rows = [r for r in results if r["modelo"] == m and r["modo"] == mode and r["nivel"] == lvl]
                cells.append(f"{sum(r['ok'] for r in rows)}/{len(rows)}")
            out.append(f"| {m} | {label} | " + " | ".join(cells) + " |")
    out += ["", "*Solo LLM*: el modelo genera toda la SQL. *Sistema completo*: enrutador de consultas",
            "verificadas + LLM. Negocio = 10/10 en el sistema completo porque las 10 necesidades se",
            "responden con SQL verificada; el dato honesto del modelo solo es la fila *solo LLM*.", "",
            "## 2. Latencia p50 por ruta (respuesta completa, sistema completo)", "",
            "| Modelo | Verificada (con redacción IA) | Verificada (por defecto) | Generada por IA | IA anclada |",
            "|---|---:|---:|---:|---:|"]
    for m in MODELS:
        def p50(source):
            v = [r["latencia_total_s"] for r in results if r["modelo"] == m and r["modo"] == "full"
                 and r["fuente"] == source and r.get("latencia_total_s") is not None]
            return f"{statistics.median(v):.1f} s" if v else "—"
        out.append(f"| {m} | {p50('verificada')} | 0.1 s | {p50('llm')} | {p50('llm_anclada')} |")
    out += ["", "\"Por defecto\" = `VERIFIED_SYNTHESIS = False`: la ruta verificada responde con una frase",
            "calculada, sin LLM (medido: 12.0 s → 0.13 s de p50; ver fase4.md).", ""]

    n6, n5, n2, n10 = (analytics.need(i) for i in (6, 5, 2, 10))
    n1, n3 = analytics.need(1), analytics.need(3)
    k = analytics.get_kpis()
    never = n6[n6["estado_inventario"] == "Nunca vendido"]
    late = n5[n5["tienda"] == "Total"].iloc[0]
    lost = n10[n10["nivel"] == "Total"].iloc[0]
    top1 = n1[n1["ranking"] == "Top ingreso neto"]
    ceded = analytics.get_kpis()["pct_descuento"]["value"]
    figures = [
        ("Capital inmovilizado en productos que nunca se vendieron (N6)",
         f"**{money(never['valor_inmovilizado'].sum())}** en {len(never)} productos "
         f"({int(never['unidades_inmovilizadas'].sum()):,} unidades)",
         "Stock > 0 sin ninguna venta completada en todo el histórico, valuado a precio de lista."),
        ("Valor de órdenes entregadas tarde (N5)",
         f"**{money(late['monto_neto'])}** en {int(late['ordenes_tarde'])} órdenes "
         f"({100 * late['ordenes_tarde'] / k['ordenes']['value']:.1f} % de las completadas)",
         "Órdenes enviadas después de la fecha requerida; valor neto de esas órdenes (no es un costo)."),
        ("Productos top en riesgo de quiebre (N2)",
         f"**{n2['producto'].nunique()} de los 20 más vendidos** con < 5 unidades en alguna tienda; "
         f"{int((n2['stock'] == 0).sum())} ya agotados",
         "Top 20 por unidades vendidas; stock por tienda sumando los product_id duplicados."),
        ("Ingreso perdido por órdenes rechazadas (N10)",
         f"**{money(lost['monto_neto_perdido'])}** en {int(lost['ordenes'])} órdenes",
         "Estado Rechazada (no existe \"cancelada\"); valor neto de esas órdenes, todo el histórico."),
        ("Descuento cedido en ventas (N1)",
         f"**{money(top1['descuento_cedido'].sum())}** solo en los 10 productos de más ingreso; "
         f"{ceded:.1f} % del bruto en total",
         "Precio de lista × cantidad × descuento, en órdenes completadas."),
        ("Concentración en Electric Bikes (N3)",
         f"**{n3.iloc[0]['vendedor']}** vende {money(n3.iloc[0]['ingreso_neto'])}, "
         f"el {100 * n3.iloc[0]['ingreso_neto'] / n3['ingreso_neto'].sum():.0f} % de la categoría",
         "Ingreso neto de ventas completadas en la categoría Electric Bikes por vendedor."),
    ]
    out += ["## 3. Las 6 cifras de negocio más fuertes", "",
            "| # | Cifra | Valor | Definición |", "|---:|---|---|---|"]
    for i, (title, value, definition) in enumerate(figures, 1):
        out.append(f"| {i} | {title} | {value} | {definition} |")
    out += ["", f"Contexto: ingreso neto de ventas completadas {money(k['ingreso_neto']['value'])} "
            f"(ene 2016 – mar 2018), {int(k['ordenes']['value']):,} órdenes completadas.", ""]
    (config.BASE_DIR / "demo" / "cifras_clave.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
