"""Fase 11: modo de red, guardián de costo y puente (todo con transporte HTTP simulado; sin red real)."""

import json
import socket

import httpx
import pytest

import bridge
import config
import cost_guard
import netmode

PROVIDERS = {
    "proveedores": {
        "gratis": {"enabled": True, "base_url": "https://api.ejemplo.test/v1/", "api_key_env": "GRATIS_KEY",
                   "key_prefix": "AIza", "modelos_gratuitos": ["modelo-free"]},
        "router": {"enabled": True, "base_url": "https://router.test/v1/", "api_key_env": "R_KEY",
                   "key_prefix": "sk-or-", "require_model_suffix": ":free",
                   "modelos_gratuitos": ["a/b:free", "a/b"]},
        "apagado": {"enabled": False, "base_url": "https://x.test/", "modelos_gratuitos": ["m"]},
    },
    "llaves_prohibidas": ["sk-ant-", "sk-proj-", "sk_live"],
}
KEY = "AIza-llave-de-prueba"


@pytest.fixture(autouse=True)
def _offline_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODO_RED", "offline")
    monkeypatch.setattr(config, "BRIDGE_ENABLED", False)
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / ".cache")


def guard(tmp_path, **kw):
    return cost_guard.CostGuard(PROVIDERS, tmp_path / "g", **kw)


def reply(text="```sql\nSELECT 1\n```", status=200, extra=None):
    def handler(request):
        body = {"choices": [{"message": {"content": text}}], **(extra or {})}
        return httpx.Response(status, json=body)
    return handler


def make_bridge(tmp_path, handler, **kw):
    calls = []
    def wrapped(request):
        calls.append(request)
        return handler(request)
    client = httpx.Client(transport=httpx.MockTransport(wrapped))
    b = bridge.OpenAICompatBridge("gratis", PROVIDERS["proveedores"]["gratis"], "modelo-free", KEY,
                                  kw.pop("guard", None) or guard(tmp_path), client, sleep=lambda s: None)
    return b, calls


MSG = [{"role": "user", "content": "hola"}]


# --- netmode -----------------------------------------------------------------------------------

def test_default_mode_is_offline_and_require_online_raises():
    assert netmode.get_mode() == "offline" and not netmode.is_online()
    with pytest.raises(netmode.OfflineError):
        netmode.require_online("llamar a un modelo grande")
    netmode.set_mode("online")
    netmode.require_online()                     # ya no lanza
    with pytest.raises(ValueError):
        netmode.set_mode("raro")


def test_unknown_mode_falls_back_to_offline(monkeypatch):
    monkeypatch.setattr(config, "MODO_RED", "ONLINE ")
    assert netmode.get_mode() == "online"
    monkeypatch.setattr(config, "MODO_RED", "cualquier-cosa")
    assert netmode.get_mode() == "offline"


@pytest.mark.parametrize("host, local", [("127.0.0.1", True), ("localhost", True), ("::1", True),
                                         ("127.0.0.5", True), ("8.8.8.8", False), ("example.com", False),
                                         ("192.168.1.10", False)])
def test_is_local_host(host, local):
    assert netmode.is_local_host(host) is local


def test_socket_guard_blocks_and_records_external_connections():
    attempts = []
    with netmode.block_external_sockets(attempts):
        s = socket.socket()
        with pytest.raises(netmode.OfflineError):
            s.connect(("93.184.216.34", 80))
        s.close()
        with pytest.raises(netmode.OfflineError):
            socket.getaddrinfo("example.com", 443)
        with pytest.raises(netmode.OfflineError):
            socket.create_connection(("example.com", 443), timeout=1)
        socket.getaddrinfo("localhost", 11434)                # localhost sí
    assert attempts and any("93.184.216.34" in str(a) for a in attempts)
    assert socket.getaddrinfo("localhost", 80)               # el parche se retira al salir


def test_full_offline_pipeline_opens_zero_external_connections(tmp_path):
    """Chat completo (harness con RAG) con LLM falso: cero conexiones fuera de localhost."""
    import database_builder
    import sql_engine as se
    database_builder.build_database()
    llm = lambda model, messages, **o: "```sql\nSELECT COUNT(*) AS n FROM customers\n```"  # noqa: E731
    attempts = []
    with netmode.block_external_sockets(attempts):
        for modo in ("base", "fewshot", "rag", "harness"):
            res = se.answer_question("¿Cuántos clientes hay?", "m", llm=llm, synthesize_answer=False,
                                     modo_contexto=modo, use_router=False)
            assert res.error is None, modo
        verified = se.answer_question("¿Cuánto dinero perdimos por pedidos rechazados?", "m", llm=llm,
                                      synthesize_answer=False, modo_contexto="harness", use_router=True)
        assert verified.source == "verificada"
    assert attempts == []


# --- cost_guard --------------------------------------------------------------------------------

def test_allowlist_rejects_unknown_and_disabled_providers(tmp_path):
    g = guard(tmp_path)
    for name in ("openai", "apagado"):
        with pytest.raises(cost_guard.CostGuardError):
            g.provider(name)
    assert g.provider("gratis")["enabled"]


def test_openrouter_models_must_end_in_free(tmp_path):
    g = guard(tmp_path)
    g.check_model("router", "a/b:free")
    with pytest.raises(cost_guard.CostGuardError, match=":free"):
        g.check_model("router", "a/b")                       # aunque esté en la lista: sin sufijo no pasa
    with pytest.raises(cost_guard.CostGuardError):
        g.check_model("gratis", "modelo-de-pago")


@pytest.mark.parametrize("key", ["sk-ant-abc", "sk-proj-abc", "sk_live_abc", "", None, "formato-raro"])
def test_billing_looking_or_malformed_keys_are_rejected(tmp_path, key):
    with pytest.raises(cost_guard.CostGuardError):
        guard(tmp_path).check_key("gratis", key)
    guard(tmp_path).check_key("gratis", KEY)


def test_quota_per_minute_and_per_day_persist_on_disk(tmp_path):
    t = [1000.0]
    g = cost_guard.CostGuard(PROVIDERS, tmp_path / "g", max_per_minute=2, max_per_day=3, now=lambda: t[0])
    g.acquire("gratis"); g.acquire("gratis")
    with pytest.raises(cost_guard.QuotaExceeded, match="minuto"):
        g.acquire("gratis")
    t[0] += 61
    g2 = cost_guard.CostGuard(PROVIDERS, tmp_path / "g", max_per_minute=2, max_per_day=3, now=lambda: t[0])
    g2.acquire("gratis")                                     # contador leído desde disco
    with pytest.raises(cost_guard.QuotaExceeded, match="diario"):
        g2.acquire("gratis")
    t[0] += 86400
    g2.acquire("gratis")                                     # al día siguiente se libera
    assert g2.used_today("gratis") == 1


def test_billing_signals_trip_the_breaker_until_reset(tmp_path):
    g = guard(tmp_path)
    with pytest.raises(cost_guard.CostGuardError):
        g.note_response(402, {})
    with pytest.raises(cost_guard.CostGuardError, match="bloqueado"):
        g.check_all("gratis", "modelo-free", KEY)
    g.reset()
    g.check_all("gratis", "modelo-free", KEY)
    with pytest.raises(cost_guard.CostGuardError):
        g.note_response(200, {"usage": {"cost": 0.002}})
    g.reset()
    g.note_response(200, {"usage": {"cost": 0}})              # costo cero no dispara nada


def test_default_yaml_enables_only_verified_free_providers():
    cfg = cost_guard.load_providers()["proveedores"]
    assert cfg["gemini"]["enabled"] and cfg["ollama"]["enabled"]
    assert not cfg["openrouter"]["enabled"] and not cfg["groq"]["enabled"]
    assert cfg["openrouter"]["require_model_suffix"] == ":free"
    for name, p in cfg.items():
        assert p.get("verificado_el"), name
        if p["enabled"] and not p.get("local"):
            assert p["fuentes"], name                         # solo se habilita con fuente anotada
    assert set(cfg["ollama"]["modelos_gratuitos"]) == set(config.SUPPORTED_MODELS)


# --- bridge ------------------------------------------------------------------------------------

def test_null_bridge_is_the_default_and_never_calls_anything():
    b = bridge.get_bridge()
    assert isinstance(b, bridge.NullBridge) and not b.available()
    with pytest.raises(bridge.BridgeUnavailable):
        b.chat(MSG)


def test_bridge_stays_null_without_key_online_or_enable_flag(tmp_path, monkeypatch):
    env = {"IAF_BRIDGE_PROVIDER": "gratis", "IAF_BRIDGE_MODEL": "modelo-free", "GRATIS_KEY": KEY}
    g = guard(tmp_path)
    monkeypatch.setattr(config, "MODO_RED", "online")
    assert isinstance(bridge.get_bridge(g, environ=env), bridge.NullBridge)          # BRIDGE_ENABLED False
    monkeypatch.setattr(config, "BRIDGE_ENABLED", True)
    assert isinstance(bridge.get_bridge(g, environ={**env, "GRATIS_KEY": ""}), bridge.NullBridge)
    assert "llave" in bridge.get_bridge(g, environ={**env, "GRATIS_KEY": ""}).reason
    assert isinstance(bridge.get_bridge(g, environ={**env, "IAF_BRIDGE_MODEL": "de-pago"}), bridge.NullBridge)
    monkeypatch.setattr(config, "MODO_RED", "offline")
    assert "offline" in bridge.get_bridge(g, environ=env).reason
    monkeypatch.setattr(config, "MODO_RED", "online")
    assert isinstance(bridge.get_bridge(g, environ=env), bridge.OpenAICompatBridge)


def test_bridge_in_offline_mode_raises_before_any_request(tmp_path):
    b, calls = make_bridge(tmp_path, reply())
    with pytest.raises(bridge.BridgeUnavailable, match="offline"):
        b.chat(MSG)
    assert calls == []


def test_bridge_online_sends_request_and_caches_the_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODO_RED", "online")
    b, calls = make_bridge(tmp_path, reply("hola mundo"))
    first = b.chat(MSG)
    assert first.texto == "hola mundo" and not first.from_cache
    req = calls[0]
    assert str(req.url) == "https://api.ejemplo.test/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body["model"] == "modelo-free" and body["temperature"] == 0 and body["messages"] == MSG
    second = b.chat(MSG)
    assert second.from_cache and len(calls) == 1             # la consulta idéntica no repite la red


def test_bridge_retries_429_then_degrades_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODO_RED", "online")
    seq = iter([429, 503, 200])
    def handler(request):
        status = next(seq)
        return httpx.Response(status, json={"choices": [{"message": {"content": "ok"}}]})
    b, calls = make_bridge(tmp_path, handler)
    assert b.chat(MSG).texto == "ok" and len(calls) == 3      # backoff y éxito al tercer intento

    always = lambda request: httpx.Response(429, json={})      # noqa: E731
    b2, calls2 = make_bridge(tmp_path, always)
    with pytest.raises(bridge.BridgeUnavailable, match="3 intentos"):
        b2.chat([{"role": "user", "content": "otra"}])
    assert len(calls2) == config.BRIDGE_MAX_RETRIES == 3


def test_bridge_degrades_on_network_failure_and_on_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODO_RED", "online")
    def boom(request):
        raise httpx.ConnectError("sin red")
    b, _ = make_bridge(tmp_path, boom)
    with pytest.raises(bridge.BridgeUnavailable, match="red"):
        b.chat(MSG)
    tight = cost_guard.CostGuard(PROVIDERS, tmp_path / "t", max_per_minute=0)
    b2, calls = make_bridge(tmp_path, reply(), guard=tight)
    with pytest.raises(bridge.BridgeUnavailable, match="minuto"):
        b2.chat(MSG)
    assert calls == []


def test_bridge_blocks_after_a_billing_signal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODO_RED", "online")
    b, calls = make_bridge(tmp_path, reply(extra={"usage": {"cost": 0.01}}))
    with pytest.raises(bridge.BridgeUnavailable, match="cobro"):
        b.chat(MSG)
    with pytest.raises(bridge.BridgeUnavailable, match="bloqueado"):
        b.chat([{"role": "user", "content": "otra"}])
    assert len(calls) == 1


def test_generate_sql_extracts_but_does_not_trust(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODO_RED", "online")
    b, _ = make_bridge(tmp_path, reply("Aquí:\n```sql\nSELECT 2 AS x\n```"))
    assert bridge.generate_sql(b, MSG) == ("SELECT 2 AS x", "ok")
    assert bridge.generate_sql(bridge.NullBridge("apagado"), MSG) == (None, "apagado")


def test_dotenv_loader_does_not_override_and_ignores_comments(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comentario\nA=1\nB='dos'\nVACIA=\nC=3\n", encoding="utf-8")
    environ = {"C": "ya"}
    assert bridge.load_dotenv(env, environ) == 2
    assert environ == {"C": "ya", "A": "1", "B": "dos"}
    assert bridge.load_dotenv(tmp_path / "nada", {}) == 0


def test_no_secrets_in_repo_files():
    from pathlib import Path
    text = (Path(config.BASE_DIR) / ".env.example").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=\n" in text                        # la llave va vacía en el ejemplo
    ignore = (Path(config.BASE_DIR) / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in ignore.split() and ".cache/" in ignore.split()
