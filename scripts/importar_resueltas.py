"""Importa ejemplos resueltos (JSON) al catálogo, validándolos. Funciona sin API ni llaves.

    python scripts/importar_resueltas.py necesidades_negativas/resueltas_claude.json --por claude-code
    python scripts/importar_resueltas.py respuesta_pegada.txt --por modelo-grande-manual

El archivo puede ser el texto tal como lo pegó un modelo grande (con ```json ... ```).
"""

import argparse
import sys

import _ruta  # noqa: F401
from pathlib import Path

from necesidades_negativas import catalogo, importador


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archivo", type=Path)
    ap.add_argument("--por", choices=catalogo.RESUELTO_POR, default="modelo-grande-manual",
                    help="quién resolvió el lote (se guarda en resuelto_por)")
    ap.add_argument("--dry-run", action="store_true", help="valida sin escribir el catálogo")
    args = ap.parse_args(argv)

    items = importador.parse_pasted_json(args.archivo.read_text(encoding="utf-8"))
    report = importador.import_entries(items, args.por, dry_run=args.dry_run)
    print(f"Agregados: {len(report['agregados'])} · duplicados: {len(report['duplicados'])} · "
          f"rechazados: {len(report['rechazados'])}")
    for question, problems in report["rechazados"]:
        print(f"  ✗ {question[:80]}\n      " + "; ".join(problems))
    return 1 if report["rechazados"] else 0


if __name__ == "__main__":
    sys.exit(main())
