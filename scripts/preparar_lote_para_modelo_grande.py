"""Exporta un .md para pegar en la versión GRATUITA de Claude / ChatGPT / Gemini (sin API ni llaves).

    python scripts/preparar_lote_para_modelo_grande.py --por-necesidad 6 --salida lote_modelo_grande.md

El modelo grande responde un JSON; pégalo en un archivo y cárgalo con:
    python scripts/importar_resueltas.py respuesta.txt --por modelo-grande-manual

Qué se envía (y solo eso): el esquema, las reglas, y por cada necesidad su pregunta y su SQL verificada.
Nunca se incluyen filas reales de la BD ni cifras de resultados.
"""

import argparse
import sys
from pathlib import Path

import _ruta  # noqa: F401

import sql_engine as se
from business_queries import BUSINESS_QUERIES, render_sql

TIPOS_AYUDA = {
    "parafrasis": "misma intención con otras palabras (español natural y coloquial); misma SQL",
    "filtro_distinto": "misma estructura con otro año, tienda, marca o categoría",
    "agregado_distinto": "otra métrica (unidades vs ingreso vs ticket promedio)",
    "casi_igual_trampa": "se parece mucho pero EXIGE otra SQL (otro JOIN, GROUP BY, estado o tabla)",
    "ruido": "faltas de ortografía, sin acentos, abreviaturas",
    "ambigua": "pregunta vaga; documenta la suposición en `notas`",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--por-necesidad", type=int, default=6)
    ap.add_argument("--salida", type=Path, default=Path("lote_modelo_grande.md"))
    args = ap.parse_args(argv)

    import yaml
    answers = yaml.safe_load((_ruta.RAIZ / "reference_answers.yaml").read_text(encoding="utf-8")) or {}
    out = [
        "# Lote para un modelo grande: necesidades negativas",
        "",
        "Eres un experto en SQL (SQLite). Para cada necesidad de negocio de abajo, escribe "
        f"**{args.por_necesidad} variantes** de la pregunta, cada una con su SQL correcta.",
        "",
        "## Esquema y reglas",
        "",
        "```",
        se.get_schema_context(),
        "```",
        "",
        "- Solo consultas SELECT/WITH de SQLite. Usa solo tablas y columnas del esquema.",
        "- Dinero: net_amount (v_order_lines) o net_total (v_orders). Ventas = order_status = 4.",
        "- Prefiere v_order_lines / v_orders; usa alias legibles en español.",
        "",
        "## Tipos de variante (mezcla varios por necesidad)",
        "",
        *[f"- `{k}`: {v}" for k, v in TIPOS_AYUDA.items()],
        "",
        "## Formato de respuesta (SOLO un JSON, una lista)",
        "",
        "```json",
        '[{"necesidad_base": "N1", "tipo": "casi_igual_trampa", "pregunta": "...", "sql": "SELECT ...", '
        '"notas": "por qué es trampa / qué suposición hiciste"}]',
        "```",
        "",
        "Cada SQL se validará automáticamente (solo lectura, debe ejecutar y dar filas). Las "
        "`casi_igual_trampa` deben dar un resultado DISTINTO al de la necesidad base.",
        "",
        "## Necesidades",
        "",
    ]
    for bq in BUSINESS_QUERIES:
        a = answers.get(bq.id) or {}
        out += [f"### {bq.id}: {bq.titulo}", f"Pregunta típica: {a.get('pregunta', bq.titulo)}",
                f"Definición: {bq.definicion}", "```sql", render_sql(bq).strip(), "```", ""]
    args.salida.write_text("\n".join(out), encoding="utf-8")
    print(f"Lote escrito en {args.salida} ({sum(map(len, out))} caracteres). Pégalo en la versión "
          "gratuita del modelo grande y guarda su JSON para importarlo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
