"""Aísla los archivos de la fase 7 (bitácora y candidatos) para que las pruebas no ensucien el repo."""

import pytest

import config
import sql_engine


@pytest.fixture(autouse=True)
def _isolated_pattern_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEARNED_PATTERNS_PATH", tmp_path / "learned_patterns.jsonl")
    monkeypatch.setattr(config, "FEWSHOT_CANDIDATES_PATH", tmp_path / "fewshot_candidates.json")
    monkeypatch.setattr(config, "REVIEWED_PATTERNS_PATH", tmp_path / "learned_patterns_reviewed.json")
    monkeypatch.setattr(sql_engine, "FEWSHOT_CANDIDATES", list(sql_engine.FEWSHOT_CANDIDATES))
