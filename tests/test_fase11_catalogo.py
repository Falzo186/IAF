"""Fase 11, módulo A: catálogo de necesidades negativas, validador, importador y generador."""

import json

import pytest

import config
import database_builder
import eval_text2sql as ev
from necesidades_negativas import catalogo, generador, importador, validador

NEEDS = [f"N{i}" for i in range(1, 11)]


@pytest.fixture(scope="module", autouse=True)
def database():
    database_builder.build_database()
    return config.DB_PATH


@pytest.fixture(scope="module")
def rows():
    return catalogo.load_catalog(solo_validados=False)


def entry(**kw):
    base = {"necesidad_base": "N8", "tipo": "parafrasis", "pregunta": "Pregunta de prueba única",
            "sql": "SELECT store_name AS tienda, COUNT(*) AS ordenes, ROUND(AVG(net_total), 2) AS "
                   "ticket_promedio FROM v_orders WHERE order_status = 4 GROUP BY store_id "
                   "ORDER BY ticket_promedio DESC",
            "resuelto_por": "claude-code", "notas": ""}
    base.update(kw)
    return base


# --- formato -----------------------------------------------------------------------------

def test_catalog_format_and_unique_ids(rows):
    assert len(rows) >= 80
    required = {"id", "necesidad_base", "tipo", "pregunta", "sql", "resuelto_por", "validado",
                "validacion", "split", "notas"}
    for r in rows:
        assert required <= set(r), r["id"]
        assert r["tipo"] in catalogo.TIPOS and r["resuelto_por"] in catalogo.RESUELTO_POR
        assert r["id"].startswith(r["necesidad_base"] + "-neg-")
        assert {"ejecuta", "filas", "sqlglot_ok", "solo_select", "comparador_vs_base"} <= set(r["validacion"])
    assert len({r["id"] for r in rows}) == len(rows)


def test_at_least_eight_variants_per_need_and_all_types_present(rows):
    for need in NEEDS:
        assert sum(r["necesidad_base"] == need for r in rows) >= 8, need
    assert {r["tipo"] for r in rows} == set(catalogo.TIPOS)
    assert sum(r["resuelto_por"] == "claude-code" for r in rows) >= 80


def test_no_duplicate_questions_and_none_from_golden(rows):
    norm = [catalogo.normalize_question(r["pregunta"]) for r in rows]
    assert len(set(norm)) == len(norm)
    assert not set(norm) & importador.golden_questions()


def test_split_is_deterministic_and_disjoint(rows):
    for r in rows:
        assert r["split"] == catalogo.split_for(r["id"])
        assert catalogo.split_for(r["id"]) == catalogo.split_for(r["id"])
    train = {r["id"] for r in rows if r["split"] == "train"}
    held = {r["id"] for r in rows if r["split"] == "heldout"}
    assert train and held and not train & held
    assert 0.2 <= len(held) / len(rows) <= 0.4
    for need in NEEDS:   # cada necesidad tiene ejemplos para entrenar y para evaluar
        assert sum(r["necesidad_base"] == need and r["split"] == "train" for r in rows) >= 5
        assert sum(r["necesidad_base"] == need and r["split"] == "heldout" for r in rows) >= 3


def test_whole_catalog_revalidates(rows):
    assert validador.validate_catalog(rows) == []
    assert all(r["validado"] for r in rows)


def test_traps_really_differ_from_base_and_paraphrases_match(rows):
    cache = {}
    for r in rows:
        if r["tipo"] == "casi_igual_trampa":
            assert r["validacion"]["comparador_vs_base"] == "distinta_a_proposito", r["id"]
        if r["tipo"] == "parafrasis":
            assert r["validacion"]["comparador_vs_base"] == "igual", r["id"]
    _, problems = validador.validate_entry(entry(tipo="casi_igual_trampa"), base_cache=cache)
    assert any("se esperaba distinta" in p for p in problems)   # una "trampa" que da lo mismo no sirve


# --- validador ---------------------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "DROP TABLE customers", "DELETE FROM customers", "UPDATE products SET list_price = 0",
    "INSERT INTO brands(brand_name) VALUES ('x')", "SELECT 1; DROP TABLE customers",
])
def test_validator_rejects_writes(sql):
    v, problems = validador.validate_entry(entry(sql=sql))
    assert problems and not v["ejecuta"]


def test_validator_rejects_bad_sql_missing_tables_and_empty_results():
    assert validador.validate_entry(entry(sql="SELEC nada FROM"))[1]
    _, problems = validador.validate_entry(entry(sql="SELECT * FROM tabla_que_no_existe"))
    assert any("no existe" in p for p in problems)
    _, empty = validador.validate_entry(entry(tipo="ambigua", sql="SELECT * FROM stores WHERE 1 = 0"))
    assert any("0 filas" in p for p in empty)
    _, allowed = validador.validate_entry(entry(tipo="ambigua", sql="SELECT * FROM stores WHERE 1 = 0",
                                                espera_vacio=True, notas="vacío a propósito"))
    assert not allowed


def test_validator_accepts_a_correct_paraphrase():
    v, problems = validador.validate_entry(entry())
    assert problems == [] and v["ejecuta"] and v["filas"] == 3 and v["comparador_vs_base"] == "igual"


# --- importador y generador --------------------------------------------------------------

def test_importer_validates_dedups_and_assigns_ids(tmp_path):
    path = tmp_path / "c.jsonl"
    items = [
        {"necesidad_base": "N8", "tipo": "parafrasis", "pregunta": "Ticket promedio de cada tienda hoy",
         "sql_desde": {"base": "N8"}},
        {"necesidad_base": "N8", "tipo": "parafrasis", "pregunta": "¡Ticket PROMEDIO de cada tienda hoy!",
         "sql_desde": {"base": "N8"}},
        {"necesidad_base": "N8", "tipo": "parafrasis", "pregunta": "Borra todo", "sql": "DROP TABLE stores"},
        {"necesidad_base": "N8", "tipo": "parafrasis", "pregunta": ev.load_golden()[10]["pregunta"],
         "sql_desde": {"base": "N8"}},
    ]
    report = importador.import_entries(items, "modelo-grande-manual", path)
    assert report["agregados"] == ["N8-neg-001"]
    assert len(report["duplicados"]) == 1 and len(report["rechazados"]) == 2
    saved = catalogo.load_catalog(path)
    assert saved[0]["validado"] and saved[0]["resuelto_por"] == "modelo-grande-manual"
    assert saved[0]["split"] == catalogo.split_for("N8-neg-001")


def test_importer_parses_json_pasted_from_a_chat():
    pasted = 'Claro, aquí tienes:\n```json\n[{"necesidad_base": "N1", "tipo": "ruido", "pregunta": "x", "sql": "SELECT 1"}]\n```\nListo.'
    assert importador.parse_pasted_json(pasted)[0]["necesidad_base"] == "N1"
    assert importador.parse_pasted_json('{"ejemplos": [{"a": 1}]}') == [{"a": 1}]
    with pytest.raises(ValueError):
        importador.parse_pasted_json("sin json")


def test_template_generator_output_passes_validation(tmp_path):
    items = generador.generar()
    assert len(items) == 50 and {i["necesidad_base"] for i in items} == set(NEEDS)
    report = importador.import_entries(items, "plantilla", tmp_path / "c.jsonl")
    assert len(report["agregados"]) >= 44
    assert all("distinta" in p[1][0] or "0 filas" in p[1][0] for p in report["rechazados"])


def test_noise_generator_is_deterministic_and_dirty():
    a = generador.ensuciar("¿Cuánto cuestan los envíos tardíos por tienda?")
    assert a == generador.ensuciar("¿Cuánto cuestan los envíos tardíos por tienda?")
    assert "¿" not in a and "í" not in a and a != "cuanto cuestan los envios tardios por tienda"


def test_catalog_hash_changes_with_content(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text(json.dumps({"id": "a"}) + "\n", encoding="utf-8")
    h1 = catalogo.catalog_hash(p)
    p.write_text(json.dumps({"id": "b"}) + "\n", encoding="utf-8")
    assert h1 != catalogo.catalog_hash(p)
    assert catalogo.catalog_hash(tmp_path / "nada") == "sin-catalogo"
