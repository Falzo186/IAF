"""Genera variantes de las necesidades y las agrega al catálogo (validadas).

    python scripts/generar_negativas.py --modo plantilla      # sin red, SQL por construcción
    python scripts/generar_negativas.py --modo api            # opcional: proveedor gratuito (modo online)

El modo `api` exige IAF_MODO_RED=online, un proveedor de bridge_providers.yaml habilitado y su llave
en el entorno. Sin eso falla con un mensaje claro y no toca el catálogo.
"""

import argparse
import sys

import _ruta  # noqa: F401

from necesidades_negativas import generador, importador


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modo", choices=["plantilla", "api"], default="plantilla")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--por-necesidad", type=int, default=3, help="solo modo api: ejemplos por necesidad")
    args = ap.parse_args(argv)

    if args.modo == "plantilla":
        items, por = generador.generar(), "plantilla"
    else:
        import bridge
        import netmode
        try:
            netmode.require_online("generar el catálogo con un modelo grande")
            items, por = bridge.generar_negativas_api(args.por_necesidad), "modelo-grande-online"
        except (netmode.OfflineError, bridge.BridgeUnavailable) as exc:
            print(f"Modo api no disponible: {exc}")
            return 2

    report = importador.import_entries(items, por, dry_run=args.dry_run)
    print(f"Agregados: {len(report['agregados'])} · duplicados: {len(report['duplicados'])} · "
          f"rechazados: {len(report['rechazados'])}")
    for question, problems in report["rechazados"]:
        print(f"  ✗ {question[:80]} — " + "; ".join(problems))
    return 0


if __name__ == "__main__":
    sys.exit(main())
