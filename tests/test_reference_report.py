"""Pruebas del PDF de respuestas de referencia (sin comparar contra el LLM: eso es una fase futura)."""

import io

import pytest
import yaml
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

import config
import reference_report as rr


def pdf_text(data: bytes) -> str:
    text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
    return " ".join(text.split())  # el PDF parte las frases en líneas: se normalizan espacios


@pytest.fixture(scope="module")
def draft_pdf():
    """PDF con el YAML del repositorio (todas las respuestas sin aprobar)."""
    return rr.generar_pdf_referencia()


def test_yaml_has_ten_needs_with_all_fields():
    data = yaml.safe_load(rr.ANSWERS_PATH.read_text(encoding="utf-8"))
    assert list(data) == rr.NEED_IDS
    for n in rr.NEED_IDS:
        assert set(rr.REQUIRED_FIELDS) <= set(data[n]), n
        assert data[n]["pregunta"].strip() and data[n]["respuesta_referencia"].strip()
    assert "aprobado: false" in rr.ANSWERS_PATH.read_text(encoding="utf-8").split("N1:")[0]  # aviso


def test_load_answers_rejects_incomplete_yaml(tmp_path):
    bad = tmp_path / "ref.yaml"
    bad.write_text("N1:\n  pregunta: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="faltan las necesidades"):
        rr.load_answers(bad)


def test_draft_pdf_contains_all_needs_and_draft_notice(draft_pdf):
    text = pdf_text(draft_pdf)
    assert draft_pdf.startswith(b"%PDF")
    assert "Bike Stores Analytics — Respuestas de referencia" in text
    assert "No es una evaluación del modelo" in text and "[Nombre 1]" in text
    assert "10 de 10 respuestas de referencia están sin" in text
    for i in range(1, 11):
        assert f"Necesidad {i} — " in text
    assert text.count("RESPUESTA DE REFERENCIA (equipo)") == 10
    assert text.count("PENDIENTE DE REVISIÓN") >= 10               # franja en cada recuadro
    assert f"sha256:{rr.db_short_hash()}" in text                    # pie de página
    assert "Apéndice A" in text and "FROM v_order_lines" in text     # SQL verificada


def test_approved_pdf_has_no_draft_marks(tmp_path):
    data = yaml.safe_load(rr.ANSWERS_PATH.read_text(encoding="utf-8"))
    for n in rr.NEED_IDS:
        data[n].update(aprobado=True, autor="Equipo de prueba", fecha_revision="2026-09-25")
    approved = tmp_path / "aprobado.yaml"
    approved.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    text = pdf_text(rr.generar_pdf_referencia(answers_path=approved))
    assert "PENDIENTE DE REVISIÓN" not in text and "sin aprobar" not in text
    assert "Autor: Equipo de prueba" in text and text.count("Aprobado") >= 10


def test_pdf_with_store_and_date_filters():
    text = pdf_text(rr.generar_pdf_referencia("Rowlett Bikes", "2017-01-01", "2017-12-31"))
    assert "Tienda: Rowlett Bikes" in text and "01/01/2017 – 31/12/2017" in text
    assert "store_name = 'Rowlett Bikes'" in text                    # filtros en la SQL del apéndice


def test_dashboard_team_panel_generates_download():
    at = AppTest.from_file(str(config.BASE_DIR / "app.py"), default_timeout=180).run()
    assert not at.exception, at.exception
    assert any("10 de 10 respuestas de referencia están sin aprobar" in w.value for w in at.warning)
    at.button(key="gen_ref_pdf").click().run()
    assert not at.exception, at.exception
    assert at.session_state["ref_pdf"].startswith(b"%PDF")
    assert at.get("download_button"), "falta el botón de descarga"
