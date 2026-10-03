"""Revisión manual de learned_patterns.jsonl (fase 7).

NO es aprendizaje automático ni se activa solo. Agrupa preguntas parecidas (similitud de texto,
sin LLM) y, por cada grupo, una persona decide:

    p  promover a few-shot -> se agrega a fewshot_candidates.json (sql_engine.FEWSHOT_CANDIDATES)
    d  descartar           -> no vuelve a aparecer
    s  saltar              -> queda pendiente
    q  salir

FEWSHOT_CANDIDATES es una lista aparte de sql_engine.FEW_SHOTS (los ejemplos del prompt de
producción). Nada la usa: si el equipo decide que un candidato vale la pena, debe moverlo A MANO
a FEW_SHOTS, igual que se hizo al revisar a mano las fallas de los modelos.

Uso:
    python review_patterns.py             # menú interactivo
    python review_patterns.py --resumen   # solo cuenta grupos pendientes
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import config
import learned_patterns
import sql_engine as se

SIMILARITY = 0.8


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text)).strip()


def similarity(a: str, b: str) -> float:
    """Similitud de texto 0..1: la mayor entre la razón de secuencia y el solapamiento de palabras."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    words_a, words_b = set(na.split()), set(nb.split())
    jaccard = len(words_a & words_b) / len(words_a | words_b)
    return max(SequenceMatcher(None, na, nb).ratio(), jaccard)


def group_patterns(patterns: list[dict], threshold: float = SIMILARITY) -> list[dict]:
    """Agrupa codiciosamente: cada pregunta entra al primer grupo cuyo representante se le parece."""
    groups: list[dict] = []
    for p in patterns:
        q = p.get("pregunta", "")
        home = next((g for g in groups if similarity(g["pregunta"], q) >= threshold), None)
        if home is None:
            home = {"pregunta": q, "items": []}
            groups.append(home)
        home["items"].append(p)
    for g in groups:
        counts = Counter(i["sql"] for i in g["items"])
        g["variantes"] = [sql for sql, _ in counts.most_common()]   # la más frecuente primero
        g["conteos"] = [counts[sql] for sql in g["variantes"]]
        g["modelos"] = sorted({i.get("modelo", "?") for i in g["items"]})
    return groups


def _read_json_list(path: Path) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_json_list(path: Path, rows: list[dict]) -> None:
    Path(path).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def reviewed(path: Path | None = None) -> list[dict]:
    return _read_json_list(path or config.REVIEWED_PATTERNS_PATH)


def pending_groups(patterns_path: Path | None = None, reviewed_path: Path | None = None,
                   threshold: float = SIMILARITY) -> list[dict]:
    """Grupos cuyo representante no se parece a ninguna pregunta ya promovida o descartada."""
    done = [r["pregunta"] for r in reviewed(reviewed_path)]
    groups = group_patterns(learned_patterns.read_patterns(patterns_path), threshold)
    return [g for g in groups if not any(similarity(g["pregunta"], q) >= threshold for q in done)]


def _record(group: dict, decision: str, reviewed_path: Path | None) -> None:
    rows = reviewed(reviewed_path)
    rows.append({"pregunta": group["pregunta"], "decision": decision,
                 "fecha": datetime.now().isoformat(timespec="seconds")})
    _write_json_list(reviewed_path or config.REVIEWED_PATTERNS_PATH, rows)


def promote(group: dict, variant: int = 0, candidates_path: Path | None = None,
            reviewed_path: Path | None = None) -> dict:
    """Agrega la SQL elegida del grupo a fewshot_candidates.json y a sql_engine.FEWSHOT_CANDIDATES.

    No toca FEW_SHOTS ni el prompt de producción.
    """
    path = Path(candidates_path or config.FEWSHOT_CANDIDATES_PATH)
    entry = {"pregunta": group["pregunta"], "sql": group["variantes"][variant],
             "modelos": group["modelos"], "veces": len(group["items"]),
             "fecha": datetime.now().isoformat(timespec="seconds")}
    rows = _read_json_list(path)
    if not any(r.get("pregunta") == entry["pregunta"] and r.get("sql") == entry["sql"] for r in rows):
        rows.append(entry)
        _write_json_list(path, rows)
    pair = (entry["pregunta"], entry["sql"])
    if pair not in se.FEWSHOT_CANDIDATES:
        se.FEWSHOT_CANDIDATES.append(pair)
    _record(group, "promovido", reviewed_path)
    return entry


def discard(group: dict, reviewed_path: Path | None = None) -> None:
    _record(group, "descartado", reviewed_path)


def show_group(group: dict, number: int, total: int, out=print) -> None:
    out(f"\n── Grupo {number}/{total} · {len(group['items'])} vez/veces · modelos: "
        f"{', '.join(group['modelos'])}")
    out(f"Pregunta: {group['pregunta']}")
    others = sorted({i["pregunta"] for i in group["items"]} - {group["pregunta"]})
    for q in others[:3]:
        out(f"   (similar) {q}")
    for n, (sql, count) in enumerate(zip(group["variantes"], group["conteos"]), start=1):
        out(f"SQL {n} ({count}×):")
        out("   " + sql.replace("\n", "\n   "))


def run_menu(patterns_path: Path | None = None, reviewed_path: Path | None = None,
             candidates_path: Path | None = None, input_fn=input, out=print) -> dict:
    groups = pending_groups(patterns_path, reviewed_path)
    stats = {"promovidos": 0, "descartados": 0, "saltados": 0}
    if not groups:
        out("No hay grupos pendientes de revisión.")
        return stats
    out("Revisión manual: esto NO activa nada solo. Los promovidos quedan en fewshot_candidates.json; "
        "para usarlos hay que moverlos a mano a sql_engine.FEW_SHOTS.")
    for n, group in enumerate(groups, start=1):
        show_group(group, n, len(groups), out)
        while True:
            choice = input_fn("[p] promover a few-shot · [pN] promover la SQL N · [d] descartar · "
                              "[s] saltar · [q] salir > ").strip().lower()
            m = re.fullmatch(r"p(\d*)", choice)
            if m:
                idx = int(m.group(1) or 1) - 1
                if 0 <= idx < len(group["variantes"]):
                    promote(group, idx, candidates_path, reviewed_path)
                    stats["promovidos"] += 1
                    out("  → agregado a los candidatos.")
                    break
                out("  Número de SQL inválido.")
            elif choice == "d":
                discard(group, reviewed_path)
                stats["descartados"] += 1
                break
            elif choice == "s":
                stats["saltados"] += 1
                break
            elif choice == "q":
                stats["saltados"] += len(groups) - n + 1
                return stats
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Revisa a mano los patrones registrados por el chat.")
    ap.add_argument("--resumen", action="store_true", help="solo cuenta los grupos pendientes")
    args = ap.parse_args(argv)

    patterns = learned_patterns.read_patterns()
    pending = pending_groups()
    print(f"{len(patterns)} patrón(es) registrado(s) · {len(pending)} grupo(s) pendiente(s) de revisión.")
    if args.resumen or not pending:
        return 0
    print(run_menu())
    return 0


if __name__ == "__main__":
    sys.exit(main())
