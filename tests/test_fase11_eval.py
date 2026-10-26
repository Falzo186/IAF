"""Fase 11, módulo E: el experimento Base | Few shot | RAG | Harness (con LLM simulado)."""

import json

import pytest

import config
import database_builder
import eval_fase11 as ex
import fewshot
from necesidades_negativas import catalogo


@pytest.fixture(scope="module", autouse=True)
def database():
    database_builder.build_database()


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / ".cache")
    monkeypatch.setattr(config, "MODO_RED", "offline")
    fewshot.reset_cache()


def sets():
    return {"golden": ex.golden_items(), "negativas_heldout": ex.heldout_items()}


def test_item_sets_have_the_expected_size_and_never_overlap():
    s = sets()
    assert len(s["golden"]) == 24
    held = catalogo.load_catalog(split="heldout")
    assert len(s["negativas_heldout"]) == len(held) and len(held) >= 30
    ids = {i["id"] for i in s["golden"]} & {i["id"] for i in s["negativas_heldout"]}
    assert not ids
    train_questions = {catalogo.normalize_question(r["pregunta"]) for r in catalogo.load_catalog(split="train")}
    for it in s["negativas_heldout"] + s["golden"]:
        assert catalogo.normalize_question(it["pregunta"]) not in train_questions


def test_heldout_items_have_a_usable_check_and_reference():
    import sql_engine as se
    for it in sets()["negativas_heldout"]:
        ref = se.execute_sql(se.validate_sql(it["sql"]))
        assert not ref.empty
        cols = it["check"].get("key_columns") or []
        assert all(c in ref.columns for c in cols), it["id"]


def test_exclusion_policies():
    item = {"id": "X", "pregunta": "q", "sql": "SELECT 1", "necesidad": "N5"}
    assert ex.exclusion_opts(item, "permisivo") == {"exclude_ids": ["X"], "exclude_questions": ["q"]}
    assert ex.exclusion_opts(item, "sin_gemelas")["exclude_sql"] == ["SELECT 1"]
    strict = ex.exclusion_opts(item, "estricto")
    assert strict["exclude_need"] == "N5" and strict["exclude_sql"] == ["SELECT 1"]
    assert "exclude_need" not in ex.exclusion_opts({**item, "necesidad": None}, "estricto")


def test_plan_runs_base_once_and_extra_policies_only_for_key_modes():
    plan = ex.plan(["base", "fewshot", "fewshot_estatico", "harness_router"], ["sin_gemelas", "permisivo", "estricto"])
    assert plan.count(("base", "n/a")) == 1
    assert ("fewshot", "estricto") in plan and ("fewshot_estatico", "permisivo") not in plan
    assert ("harness_router", "sin_gemelas") in plan and ("harness_router", "estricto") not in plan


def test_simulated_run_scores_everything_and_writes_all_outputs(tmp_path):
    s = sets()
    items = [i for v in s.values() for i in v]
    attempts = []
    from netmode import block_external_sockets
    with block_external_sockets(attempts):
        results = ex.run_experiment(["oraculo"], ["base", "fewshot", "rag", "harness", "harness_router"],
                                    ["golden", "negativas_heldout"], ["sin_gemelas"], 2, "produccion", 1,
                                    lambda _m: ex.oracle_for(items), s)
    assert attempts == []
    assert len(results) == 5 * (24 + len(s["negativas_heldout"]))
    plain = [r for r in results if r["modo"] != "harness_router"]
    assert all(r["ok"] for r in plain)
    assert all(r["politica"] == ("n/a" if r["modo"] == "base" else "sin_gemelas") for r in results)

    meta = ex.build_meta(type("A", (), dict(red="offline", simulado=True, max_intentos=2, reparacion="produccion",
                                            repeticiones=1, modelos=["oraculo"], modos=["base"],
                                            politicas=["sin_gemelas"], conjuntos=list(s), consistencia=1))(), s, attempts)
    out = tmp_path / "out"
    ex.write_outputs(results, meta, out)
    for name in ("resultados.json", "resultados.csv", "tabla_comparativa.md", "grafica_comparativa.png"):
        assert (out / name).stat().st_size > 0, name
    md = (out / "tabla_comparativa.md").read_text(encoding="utf-8")
    assert "SIMULADO" in md and "| Modelo | Conjunto | Base | Few shot | RAG | Harness |" in md
    assert "conexiones externas intentadas: **0**" in md
    saved = json.loads((out / "resultados.json").read_text(encoding="utf-8"))
    assert saved["meta"]["catalogo_hash"] == catalogo.catalog_hash() and saved["meta"]["simulado"] is True


def test_the_model_never_receives_reference_sql_through_the_eval_path():
    """Camino real de run_one: el prompt de cada modo no lleva la SQL de la referencia ni preguntas heldout."""
    held_q = {catalogo.normalize_question(i["pregunta"]) for i in sets()["negativas_heldout"]}
    seen = []

    def spy(model, messages, **_):
        seen.append(messages[0]["content"])
        return "```sql\nSELECT 1 AS x\n```"

    for item in sets()["golden"][:12] + sets()["negativas_heldout"][:12]:
        for modo in ("fewshot", "fewshot_estatico", "rag", "harness"):
            seen.clear()
            ex.run_one(item, "m", modo, "sin_gemelas", spy, {}, 1, "produccion")
            prompt = catalogo.normalize_sql(seen[0])
            assert catalogo.normalize_sql(item["sql"]) not in prompt, (item["id"], modo)
            assert not any(q in catalogo.normalize_question(seen[0]) for q in held_q if q != catalogo.normalize_question(item["pregunta"])), (item["id"], modo)


def test_sign_test_and_paired_table():
    assert ex.sign_test_p(0, 0) == 1.0
    assert ex.sign_test_p(10, 0) == pytest.approx(2 / 1024)
    assert ex.sign_test_p(3, 3) == 1.0
    rows = []
    for i in range(10):
        for modo, ok in (("base", False), ("fewshot", i < 8)):
            rows.append({"modelo": "m", "modo": modo, "politica": "n/a" if modo == "base" else "sin_gemelas",
                         "conjunto": "golden", "id": f"G{i}", "ok": ok})
    line = [l for l in ex.paired_table(rows, ["m"]) if "Few shot" in l][0]
    assert "| 8 | 0 | 2 |" in line and "0.008" in line


def test_resume_skips_finished_cells(tmp_path):
    s = {"golden": ex.golden_items()[:3]}
    items = s["golden"]
    first = ex.run_experiment(["o"], ["base"], ["golden"], ["sin_gemelas"], 2, "produccion", 1,
                              lambda _m: ex.oracle_for(items), s)
    done = {(r["modelo"], r["modo"], r["politica"], r["conjunto"], r["id"], r["repeticion"]) for r in first}
    again = ex.run_experiment(["o"], ["base", "rag"], ["golden"], ["sin_gemelas"], 2, "produccion", 1,
                              lambda _m: ex.oracle_for(items), s, done=done)
    assert {r["modo"] for r in again} == {"rag"} and len(again) == 3


def test_cli_fails_cleanly_without_ollama_and_smoke_run_works(tmp_path, monkeypatch, capsys):
    import ollama_manager as om
    monkeypatch.setattr(om, "is_server_up", lambda: False)
    monkeypatch.setattr(om, "try_start_server", lambda: False)
    assert ex.main(["--modelos", "qwen2.5:1.5b", "--salida", str(tmp_path / "a")]) == 2
    assert "Ollama no está disponible" in capsys.readouterr().out
    monkeypatch.setattr(om, "is_server_up", lambda: True)
    monkeypatch.setattr(om, "is_model_available", lambda m: False)
    assert ex.main(["--modelos", "llama3.2:1b", "--salida", str(tmp_path / "b")]) == 2
    assert "sin descargar" in capsys.readouterr().out
    out = tmp_path / "sim"
    assert ex.main(["--simulado", "--modelos", "qwen2.5:1.5b", "--modos", "base", "rag", "--conjuntos", "golden",
                    "--salida", str(out)]) == 0
    assert "SIMULADO" in (out / "tabla_comparativa.md").read_text(encoding="utf-8")
    assert ex.main(["--solo-reporte", "--salida", str(out)]) == 0
