"""Fase 11, módulos B y C: few-shot y RAG léxico (sin Ollama, sin red)."""

import json

import pytest

import config
import database_builder
import eval_text2sql as ev
import fewshot
import rag
import sql_engine as se
from necesidades_negativas import catalogo

ITEMS = {it["id"]: it for it in ev.load_golden()}


@pytest.fixture(scope="module", autouse=True)
def database():
    database_builder.build_database()


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / ".cache")
    fewshot.reset_cache()
    yield
    fewshot.reset_cache()


HELDOUT_QUESTIONS = {catalogo.normalize_question(r["pregunta"]) for r in catalogo.load_catalog(split="heldout")}


# --- few-shot ------------------------------------------------------------------------------

def test_select_fewshot_respects_k_and_returns_train_only():
    for k in (1, 2, 3, 5):
        found = fewshot.select_fewshot("ticket promedio por tienda", k=k)
        assert len(found) == k
    train_ids = {r["id"] for r in catalogo.load_catalog(split="train")}
    assert {e["id"] for e in fewshot.select_fewshot("¿cuánto perdimos por pedidos rechazados?")} <= train_ids


def test_heldout_can_never_be_requested():
    with pytest.raises(ValueError):
        fewshot.select_fewshot("ticket promedio", split="heldout")


def test_exclude_ids_questions_sql_and_need():
    top = fewshot.select_fewshot("cuánto cuestan los envíos tardíos por tienda", k=3)
    assert top and top[0]["necesidad_base"] == "N5"
    assert top[0]["id"] not in {e["id"] for e in
                                fewshot.select_fewshot("cuánto cuestan los envíos tardíos por tienda",
                                                       k=3, exclude_ids=[top[0]["id"]])}
    assert top[0]["id"] not in {e["id"] for e in fewshot.select_fewshot(
        "cuánto cuestan los envíos tardíos por tienda", k=3, exclude_questions=[top[0]["pregunta"]])}
    assert top[0]["sql"] not in {e["sql"] for e in fewshot.select_fewshot(
        "cuánto cuestan los envíos tardíos por tienda", k=5, exclude_sql=[top[0]["sql"]])}
    assert "N5" not in {e["necesidad_base"] for e in fewshot.select_fewshot(
        "cuánto cuestan los envíos tardíos por tienda", k=5, exclude_need="N5")}


def test_format_examples_obeys_the_char_budget():
    found = fewshot.select_fewshot("ticket promedio por tienda", k=5)
    text, used = fewshot.format_examples(found, max_chars=700)
    assert len(text) - len(fewshot.HEADER) <= 700 + 4 and len(used) < len(found)
    assert fewshot.format_examples(found, max_chars=10) == ("", [])
    full, used_all = fewshot.format_examples(found)
    assert len(full) <= config.FEWSHOT_MAX_CHARS + len(fewshot.HEADER) + 8
    assert fewshot.HEADER in full and "```sql" in full


def test_static_fewshot_is_fixed_and_diverse():
    a = fewshot.select_fewshot("una pregunta", modo="estatico")
    b = fewshot.select_fewshot("otra pregunta muy distinta", modo="estatico")
    assert [e["id"] for e in a] == [e["id"] for e in b]
    assert len({e["necesidad_base"] for e in a}) == len(a) == config.FEWSHOT_K
    skipped = fewshot.select_fewshot("x", modo="estatico", exclude_ids=[a[0]["id"]])
    assert a[0]["id"] not in {e["id"] for e in skipped} and len(skipped) == config.FEWSHOT_K


# --- RAG -------------------------------------------------------------------------------------

@pytest.mark.parametrize("question, need", [
    ("¿Cuánto nos cuesta el retraso de los pedidos por tienda?", "N5"),
    ("quien vende mas e-bikes", "N3"),
    ("kien vende mas bicis electricas", "N3"),                         # ruido ortográfico
    ("QUÉ PRODUCTOS LLEVAN MESES SIN VENDERSE", "N6"),                # mayúsculas y acentos
    ("valor promedio de un pedido en cada tienda", "N8"),
    ("clientes que combinan marcas diferentes en un pedido", "N7"),
])
def test_rag_top1_matches_control_paraphrases(question, need):
    hits = fewshot.get_retriever("rag").query(question, k=3)
    assert hits and hits[0].ejemplo["necesidad_base"] == need, [(h.id, h.score) for h in hits]


def test_rag_threshold_discards_weak_matches():
    r = fewshot.get_retriever("rag")
    assert r.query("receta de paella valenciana con mariscos", k=3, min_score=0.5) == []
    assert r.query("ticket promedio por tienda", k=3, min_score=0.5)
    scores = [h.score for h in r.query("ticket promedio por tienda", k=5)]
    assert scores == sorted(scores, reverse=True)


def test_rag_indexes_train_verified_and_patterns_but_never_heldout(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FEWSHOT_CANDIDATES_PATH", tmp_path / "cand.json")
    (tmp_path / "cand.json").write_text(json.dumps([{"pregunta": "Pregunta de patrón aprobado",
                                                      "sql": "SELECT 1"}]), encoding="utf-8")
    docs = rag.Retriever.collect_docs()
    origins = {d["origen"] for d in docs}
    assert origins == {"catalogo", "verificada", "patron"}
    assert all(d["split"] == "train" for d in docs)
    assert not {catalogo.normalize_question(d["pregunta"]) for d in docs} & HELDOUT_QUESTIONS
    assert {f"N{i}" for i in range(1, 11)} <= {d["id"] for d in docs}


def test_rag_cache_is_reused_and_invalidated_when_catalog_changes(tmp_path):
    rows = [dict(r) for r in catalogo.load_catalog(split="train")][:12]
    cat, cache = tmp_path / "cat.jsonl", tmp_path / "idx.json"
    catalogo.write_catalog(rows, cat)
    first = rag.Retriever.build(include_verified=False, include_patterns=False, catalog_path=cat, cache_path=cache)
    assert cache.exists()
    cached_text = cache.read_text(encoding="utf-8")
    again = rag.Retriever.build(include_verified=False, include_patterns=False, catalog_path=cat, cache_path=cache)
    assert again.signature == first.signature and cache.read_text(encoding="utf-8") == cached_text
    rows.append({**rows[0], "id": "N1-neg-999", "pregunta": "Pregunta nueva que cambia el catálogo"})
    catalogo.write_catalog(rows, cat)
    changed = rag.Retriever.build(include_verified=False, include_patterns=False, catalog_path=cat, cache_path=cache)
    assert changed.signature != first.signature and len(changed.docs) == len(first.docs) + 1


def test_schema_fragment_trims_unneeded_tables_but_keeps_valid_values():
    schema = se.get_schema_context()
    hits = fewshot.get_retriever("rag").query("ticket promedio por tienda", k=3)
    frag = rag.schema_fragment("ticket promedio por tienda", hits, schema)
    assert len(frag) < len(schema)
    assert "v_order_lines(" in frag and "v_orders(" in frag and "Valores válidos" in frag
    assert "customers(" not in frag
    stock_frag = rag.schema_fragment("stock bajo", fewshot.get_retriever("rag").query("productos con poco stock", k=3), schema)
    assert "stocks(" in stock_frag and "products(" in stock_frag and "stores(" in stock_frag   # vecinos para el JOIN
    assert rag.schema_fragment("x", [], "sin bloques") == "sin bloques"


# --- anti-fuga -------------------------------------------------------------------------------

class CapturingLLM:
    def __init__(self):
        self.prompts = []

    def __call__(self, model, messages, **opts):
        self.prompts.append(messages[0]["content"])
        return "```sql\nSELECT 1 AS x\n```"


def policy(item):
    """La política oficial de evaluación: pregunta y SQL idéntica a la referencia fuera."""
    return {"exclude_ids": [item["id"]], "exclude_questions": [item["pregunta"]],
            "exclude_sql": [item["sql"]]}


@pytest.mark.parametrize("modo", ["fewshot", "rag", "harness"])
def test_prompts_never_contain_reference_sql_or_heldout(modo):
    for item in ITEMS.values():
        llm = CapturingLLM()
        se.answer_question(item["pregunta"], "m", llm=llm, use_router=False, synthesize_answer=False,
                           max_attempts=1, modo_contexto=modo, contexto_opts=policy(item))
        prompt = llm.prompts[0]
        norm_prompt = catalogo.normalize_sql(prompt)
        assert catalogo.normalize_sql(item["sql"]) not in norm_prompt, (modo, item["id"])
        assert not any(q in catalogo.normalize_question(prompt) for q in HELDOUT_QUESTIONS), (modo, item["id"])


def test_strict_mode_leaves_out_every_sibling_of_the_need():
    item = ITEMS["N5"]
    llm = CapturingLLM()
    se.answer_question(item["pregunta"], "m", llm=llm, use_router=False, synthesize_answer=False,
                       max_attempts=1, modo_contexto="rag",
                       contexto_opts={**policy(item), "exclude_need": "N5"})
    for r in catalogo.load_catalog(split="train"):
        if r["necesidad_base"] == "N5":
            assert r["pregunta"] not in llm.prompts[0]
