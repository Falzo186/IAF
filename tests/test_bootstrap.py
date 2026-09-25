"""Pruebas de bootstrap.py sin red: hash, puertos, estados de Ollama, modo sin IA y flags."""

import socket

import pytest

import bootstrap as bs
import pull_log


# --- Hash de requirements -------------------------------------------------------

def test_requirements_hash_controls_reinstall(tmp_path):
    req = tmp_path / "requirements.txt"
    marker = tmp_path / ".req_hash"
    req.write_text("pandas>=2.2\nstreamlit>=1.40\n", encoding="utf-8")
    assert bs.needs_install(req, marker)                       # sin marca: instala
    marker.write_text(bs.file_hash(req), encoding="utf-8")
    assert not bs.needs_install(req, marker)                   # sin cambios: no reinstala
    req.write_bytes(b"pandas>=2.2\r\nstreamlit>=1.40  \r\n")   # CRLF y espacios: mismo contenido
    assert not bs.needs_install(req, marker)
    req.write_text("pandas>=2.2\nstreamlit>=1.40\nplotly>=5\n", encoding="utf-8")
    assert bs.needs_install(req, marker)                       # cambió: reinstala


def test_runtime_requirements_exclude_dev_tools():
    runtime = (bs.BASE_DIR / "requirements.txt").read_text(encoding="utf-8").lower()
    dev = (bs.BASE_DIR / "requirements-dev.txt").read_text(encoding="utf-8").lower()
    assert "pytest" not in runtime and "playwright" not in runtime
    assert "-r requirements.txt" in dev and "pytest" in dev and "playwright" in dev


# --- Puertos --------------------------------------------------------------------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_free_port_is_returned_as_is():
    port = _free_port()
    assert bs.find_free_port(port) == port


def test_busy_port_moves_to_next():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert bs.port_in_use(port)
        chosen = bs.find_free_port(port)
        assert chosen > port and not bs.port_in_use(chosen)


# --- Ollama ---------------------------------------------------------------------

@pytest.mark.parametrize("api, binary, expected", [
    (True, "C:/ollama.exe", "up"),
    (False, "C:/ollama.exe", "stopped"),
    (False, None, "missing"),
])
def test_ollama_states(api, binary, expected):
    assert bs.ollama_state("http://x", api_up=lambda _h: api, binary=lambda: binary) == expected


def test_sin_ia_flag_skips_ollama(monkeypatch):
    monkeypatch.setattr(bs, "ollama_state", lambda *_a, **_k: pytest.fail("no debe consultar Ollama"))
    assert bs.ensure_ollama(sin_ia=True) == (False, None)


def test_missing_ollama_non_interactive_falls_back_to_sin_ia(monkeypatch):
    monkeypatch.setattr(bs, "ollama_state", lambda host: "missing")
    monkeypatch.setattr(bs, "install_ollama", lambda: pytest.fail("no debe instalar sin preguntar"))
    assert bs.ensure_ollama(sin_ia=False, interactive=False) == (False, None)


def test_stopped_ollama_that_fails_to_start_is_sin_ia(monkeypatch):
    monkeypatch.setattr(bs, "ollama_state", lambda host: "stopped")
    monkeypatch.setattr(bs, "ollama_binary", lambda: "ollama")
    monkeypatch.setattr(bs, "start_ollama", lambda binary, host: None)
    assert bs.ensure_ollama(sin_ia=False, interactive=False) == (False, None)


def test_up_ollama_with_missing_model_pulls_in_background(monkeypatch):
    pulled = []
    monkeypatch.setattr(bs, "ollama_state", lambda host: "up")
    monkeypatch.setattr(bs, "model_available", lambda host, model: False)
    monkeypatch.setattr(bs, "pull_in_background", lambda py, model: pulled.append(model))
    assert bs.ensure_ollama(sin_ia=False) == (True, None)
    assert pulled == [bs.read_config()["DEFAULT_MODEL"]]


def test_ask_yes_no(monkeypatch):
    class TTY:
        def isatty(self):
            return True
    monkeypatch.setattr(bs.sys, "stdin", TTY())
    assert bs.ask_yes_no("¿Instalar?", input_fn=lambda _p: "") is True       # [S/n] por defecto sí
    assert bs.ask_yes_no("¿Instalar?", input_fn=lambda _p: "n") is False
    assert bs.ask_yes_no("¿Instalar?", input_fn=lambda _p: "sí") is True


def test_read_config_matches_config_module():
    import config
    assert bs.read_config()["DEFAULT_MODEL"] == config.DEFAULT_MODEL


# --- Flags ----------------------------------------------------------------------

def test_flags():
    a = bs.parse_args([])
    assert (a.sin_ia, a.reset, a.no_browser, a.smoke, a.port) == (False, False, False, False, 8501)
    a = bs.parse_args(["--sin-ia", "--reset", "--no-browser", "--smoke"])
    assert (a.sin_ia, a.reset, a.no_browser, a.smoke) == (True, True, True, True)
    with pytest.raises(SystemExit):
        bs.parse_args(["--desconocido"])


# --- Progreso de descargas en segundo plano -------------------------------------

def test_pull_progress_from_lock_and_log(tmp_path):
    model = "qwen2.5:1.5b"
    log, lock = pull_log.paths(model, tmp_path)
    assert log.name == "pull_qwen2.5_1.5b.log" and lock.name == "pull_qwen2.5_1.5b.lock"
    assert pull_log.progress(model, tmp_path) is None                  # sin .lock: no hay descarga
    lock.write_text("1", encoding="utf-8")
    assert pull_log.progress(model, tmp_path) == 0.0                   # empezó, sin porcentaje aún
    log.write_text("pulling manifest\t\npulling abc\t12.5\npulling abc\t47.0\nverifying\t\n",
                   encoding="utf-8")
    assert pull_log.progress(model, tmp_path) == 47.0
    lock.unlink()
    assert pull_log.progress(model, tmp_path) is None
