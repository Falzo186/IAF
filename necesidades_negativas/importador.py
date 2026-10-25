"""Importador: convierte ejemplos resueltos (de Claude Code, de un modelo grande o de plantilla) en
entradas del catálogo, pasando todas por el validador. Sin red.

Entrada (lista de objetos):
    {"necesidad_base": "N1", "tipo": "parafrasis", "pregunta": "...", "sql": "SELECT ..."}
    {"necesidad_base": "N1", "tipo": "parafrasis", "pregunta": "...", "sql_desde": {"base": "N1",
        "store_name": "Baldwin Bikes", "date_from": "2017-01-01", "date_to": "2017-12-31"}}
`sql_desde` expande la SQL verificada de la necesidad con business_queries.render_sql (así los
filtros salen por construcción). Campos opcionales: notas, espera_vacio, comparador_esperado.

Nunca entra al catálogo lo que no valida (regla 7): sin `validado: true` no se guarda.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import config
from business_queries import BY_ID, render_sql

from . import catalogo, validador


def golden_questions() -> set[str]:
    import eval_text2sql as ev
    return {catalogo.normalize_question(it["pregunta"]) for it in ev.load_golden()}


def expand_sql(item: dict) -> str:
    if item.get("sql"):
        return str(item["sql"]).strip()
    spec = item.get("sql_desde")
    if spec:
        return render_sql(BY_ID[spec["base"]], store_name=spec.get("store_name"),
                          date_from=spec.get("date_from"), date_to=spec.get("date_to"))
    return ""


def parse_pasted_json(text: str) -> list[dict]:
    """Acepta el JSON tal como lo pega un modelo grande: con ```json ... ``` y con texto alrededor."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith(("[", "{")):
        start = min([i for i in (text.find("["), text.find("{")) if i >= 0], default=-1)
        if start < 0:
            raise ValueError("No se encontró JSON en el texto pegado.")
        text = text[start:]
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("ejemplos") or data.get("items") or [data]
    if not isinstance(data, list):
        raise ValueError("Se esperaba una lista de ejemplos.")
    return data


def import_entries(items: list[dict], resuelto_por: str, catalog_path: Path | None = None,
                   db_path: Path = config.DB_PATH, dry_run: bool = False) -> dict:
    """Valida y agrega. Devuelve {"agregados": [...], "rechazados": [(pregunta, motivos)], "duplicados": [...]}."""
    rows = catalogo.load_catalog(catalog_path, solo_validados=False)
    seen = {catalogo.normalize_question(r["pregunta"]) for r in rows}
    banned = golden_questions()
    cache: dict = {}
    report = {"agregados": [], "rechazados": [], "duplicados": []}
    for item in items:
        question = str(item.get("pregunta", "")).strip()
        nq = catalogo.normalize_question(question)
        if nq in seen:
            report["duplicados"].append(question)
            continue
        if nq in banned:
            report["rechazados"].append((question, ["es una pregunta del golden set (contaminación)"]))
            continue
        need = item.get("necesidad_base")
        entry = {
            "id": catalogo.next_id(rows, need) if need in BY_ID else "?-neg-000",
            "necesidad_base": need, "tipo": item.get("tipo"), "pregunta": question,
            "sql": expand_sql(item), "resuelto_por": item.get("resuelto_por") or resuelto_por,
            "validado": False, "validacion": {}, "split": "train", "notas": item.get("notas", ""),
        }
        for key in ("espera_vacio", "comparador_esperado"):
            if key in item:
                entry[key] = item[key]
        validation, problems = validador.validate_entry(entry, db_path, cache)
        if problems:
            report["rechazados"].append((question, problems))
            continue
        entry["validacion"], entry["validado"] = validation, True
        entry["split"] = catalogo.split_for(entry["id"])
        rows.append(entry)
        seen.add(nq)
        report["agregados"].append(entry["id"])
    if not dry_run and report["agregados"]:
        catalogo.write_catalog(rows, catalog_path)
    return report
