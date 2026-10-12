"""Evidencia del avance: el LLM local resuelve 5 necesidades y se guarda 1 JSON por pregunta.

Usa sql_engine.answer_question(..., use_router=False): el enrutador de consultas verificadas
queda DESACTIVADO, así que la SQL la genera el propio LLM (Ollama, config.DEFAULT_MODEL).
Los resultados se guardan tal cual salgan, incluidos los fallos: es evidencia real.

Uso:  python avance_json.py
Salida: avance/json/<id>.json y avance/resumen.txt
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import config
import sql_engine as se

OUT_DIR = config.BASE_DIR / "avance"
JSON_DIR = OUT_DIR / "json"
MAX_ROWS = 20

PREGUNTAS = [
    ("N02_riesgo_quiebre_stock", "¿Qué productos se venden mucho pero están a punto de agotarse?"),
    ("N05_costo_ineficiencia_logistica", "¿Cuál es el monto de las órdenes entregadas con retraso, por tienda?"),
    ("N06_inventario_inactivo", "¿Cuánto dinero tenemos parado en inventario que nunca se ha vendido?"),
    ("N08_ticket_promedio_sucursal", "¿Cuál es el ticket promedio por tienda?"),
    ("N10_impacto_cancelaciones", "¿Cuánto ingreso se perdió por órdenes rechazadas?"),
]


def filas(df) -> list[dict]:
    """Primeras MAX_ROWS filas con tipos nativos de JSON (sin numpy)."""
    if df is None:
        return []
    return json.loads(df.head(MAX_ROWS).to_json(orient="records", force_ascii=False))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    modelo = config.DEFAULT_MODEL
    print(f"Avance — LLM local {modelo} generando su propia SQL (enrutador desactivado)\n")

    resumen = []
    for nid, pregunta in PREGUNTAS:
        print(f"Consultando {nid}…", flush=True)
        t0 = time.perf_counter()
        r = se.answer_question(pregunta, model=modelo, use_router=False)
        segundos = round(time.perf_counter() - t0, 2)
        data = {
            "necesidad_id": nid,
            "pregunta": pregunta,
            "modelo": modelo,
            "sql_generada": r.sql,
            "filas": filas(r.df),
            "respuesta_lenguaje_natural": r.answer,
            "tiempo_segundos": segundos,
            "generado_en": datetime.now().isoformat(timespec="seconds"),
        }
        if r.error:  # se reporta tal cual: no se ajusta nada para forzar que pase
            data["error"] = r.error
        (JSON_DIR / f"{nid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
        bloque = (f"[{nid}] {pregunta}\n"
                  f"  Tiempo: {segundos:.1f} s · intentos de SQL: {r.attempts}"
                  f"{' · ERROR: ' + r.error.splitlines()[0][:160] if r.error else ''}\n"
                  f"  Respuesta: {r.answer}\n")
        print(bloque, flush=True)
        resumen.append(bloque)

    (OUT_DIR / "resumen.txt").write_text(
        f"Avance — {modelo} · {datetime.now():%Y-%m-%d %H:%M} · enrutador desactivado "
        f"(use_router=False)\n\n" + "\n".join(resumen), encoding="utf-8")
    print(f"Archivos: {JSON_DIR} (5 JSON) y {OUT_DIR / 'resumen.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
