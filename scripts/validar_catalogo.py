"""Revalida todo el catálogo (ids, duplicados, split, SQL solo lectura, comparador). Sale con 1 si hay inválidos.

    python scripts/validar_catalogo.py
"""

import sys

import _ruta  # noqa: F401

from necesidades_negativas import catalogo, validador


def main() -> int:
    rows = catalogo.load_catalog(solo_validados=False)
    bad = validador.validate_catalog(rows)
    print(f"{len(rows)} entradas · {len(bad)} inválidas")
    for entry_id, problems in bad:
        print(f"  ✗ {entry_id}: " + "; ".join(problems))
    s = catalogo.stats(rows)
    print("por necesidad:", s["necesidad_base"])
    print("por tipo:", s["tipo"])
    print("split:", s["split"], "· resuelto_por:", s["resuelto_por"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
