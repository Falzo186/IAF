"""Pruebas de ollama_manager sin servidor: apuntan a un puerto local cerrado."""

import socket
import time

import pytest

import config
import ollama_manager as om


@pytest.fixture
def dead_host(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(config, "OLLAMA_HOST", f"http://127.0.0.1:{port}")
    om.get_client.cache_clear()
    yield
    om.get_client.cache_clear()


def test_is_server_up_false_and_fast(dead_host):
    t0 = time.monotonic()
    assert om.is_server_up() is False
    assert time.monotonic() - t0 < 3


@pytest.mark.parametrize("call", [
    lambda: om.list_local_models(),
    lambda: om.chat("qwen2.5:1.5b", [{"role": "user", "content": "hola"}]),
    lambda: list(om.pull_model("qwen2.5:1.5b")),
    lambda: om.unload_model("qwen2.5:1.5b"),
    lambda: om.loaded_models(),
])
def test_connection_errors_become_ollama_unavailable(dead_host, call):
    with pytest.raises(om.OllamaUnavailable, match="No se pudo conectar"):
        call()


def test_client_is_singleton():
    assert om.get_client() is om.get_client()


def test_chat_uses_keep_alive(monkeypatch):
    sent = {}

    class Client:
        def chat(self, **kwargs):
            sent.update(kwargs)
            return type("R", (), {"message": type("M", (), {"content": "ok"})()})()

    monkeypatch.setattr(om, "get_client", lambda: Client())
    assert om.chat("qwen2.5:1.5b", [{"role": "user", "content": "hola"}]) == "ok"
    assert sent["keep_alive"] == config.KEEP_ALIVE == "60m"
