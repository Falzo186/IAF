"""Puente opcional a un modelo grande de capa gratuita (fase 11). Desactivado por defecto.

`get_bridge()` devuelve un NullBridge salvo que TODO esto se cumpla: config.BRIDGE_ENABLED, modo de
red online, proveedor habilitado en bridge_providers.yaml, modelo gratuito y llave con el formato
del proveedor. Sin red, sin llave o sin cuota, el puente se desactiva sin error y quien llama sigue en
offline. Un solo cliente HTTP (`OpenAICompatBridge`) sirve a cualquier proveedor con API compatible
con OpenAI.

Qué se envía: el esquema de la base, las reglas y las preguntas del catálogo. Nunca filas reales.
La SQL que devuelve se valida igual que cualquier otra (solo SELECT, sqlglot, solo lectura).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import config
import netmode
from cost_guard import CostGuard, CostGuardError, QuotaExceeded


class BridgeUnavailable(RuntimeError):
    """El puente no puede responder (desactivado, sin red, sin llave, sin cuota o con error del proveedor)."""


@dataclass
class BridgeResult:
    texto: str
    provider: str
    model: str
    from_cache: bool = False


def load_dotenv(path: Path | None = None, environ=None) -> int:
    """Carga KEY=VALUE de .env en el entorno sin pisar variables ya definidas. Devuelve cuántas cargó."""
    environ = os.environ if environ is None else environ
    path = Path(path or config.BASE_DIR / ".env")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    loaded = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in environ:
            environ[key] = value
            loaded += 1
    return loaded


class NullBridge:
    """Puente por defecto: nunca llama a nada."""
    name = "ninguno"

    def __init__(self, reason: str = "puente desactivado"):
        self.reason = reason

    def available(self) -> bool:
        return False

    def chat(self, messages: list[dict]) -> BridgeResult:
        raise BridgeUnavailable(self.reason)


class OpenAICompatBridge:
    def __init__(self, provider: str, cfg: dict, model: str, api_key: str | None, guard: CostGuard,
                 client=None, sleep=time.sleep):
        self.name, self.cfg, self.model, self.api_key = provider, cfg, model, api_key
        self.guard, self._client, self.sleep = guard, client, sleep
        self.reason = ""

    def available(self) -> bool:
        return True

    @property
    def client(self):
        if self._client is None:
            import httpx
            self._client = httpx.Client(timeout=config.BRIDGE_TIMEOUT_S)
        return self._client

    def chat(self, messages: list[dict]) -> BridgeResult:
        import httpx
        try:
            netmode.require_online("llamar a un modelo grande")
            self.guard.check_all(self.name, self.model, self.api_key)
        except (netmode.OfflineError, CostGuardError) as exc:
            raise BridgeUnavailable(str(exc)) from exc

        key = self.guard.cache_key(self.name, self.model, messages)
        cached = self.guard.cache_get(key)
        if cached is not None:
            return BridgeResult(cached, self.name, self.model, from_cache=True)
        try:
            self.guard.acquire(self.name)
        except QuotaExceeded as exc:
            raise BridgeUnavailable(str(exc)) from exc

        url = self.cfg["base_url"].rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {"model": self.model, "messages": messages, "temperature": 0}
        last = "sin respuesta"
        for attempt in range(1, config.BRIDGE_MAX_RETRIES + 1):
            try:
                resp = self.client.post(url, json=body, headers=headers, timeout=config.BRIDGE_TIMEOUT_S)
            except httpx.HTTPError as exc:
                last = f"error de red: {type(exc).__name__}"
            else:
                try:
                    data = resp.json()
                except ValueError:
                    data = None
                try:
                    self.guard.note_response(resp.status_code, data)
                except CostGuardError as exc:
                    raise BridgeUnavailable(str(exc)) from exc
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = f"HTTP {resp.status_code}"
                elif resp.status_code >= 400:
                    raise BridgeUnavailable(f"El proveedor respondió HTTP {resp.status_code}.")
                else:
                    try:
                        text = data["choices"][0]["message"]["content"] or ""
                    except (TypeError, KeyError, IndexError) as exc:
                        raise BridgeUnavailable("Respuesta del proveedor con formato inesperado.") from exc
                    self.guard.cache_put(key, text)
                    return BridgeResult(text, self.name, self.model)
            if attempt < config.BRIDGE_MAX_RETRIES:
                self.sleep(min(2 ** attempt, 8))          # backoff ante 429 / 5xx / red
        raise BridgeUnavailable(f"Sin respuesta tras {config.BRIDGE_MAX_RETRIES} intentos ({last}).")


def get_bridge(guard: CostGuard | None = None, client=None, environ=None, sleep=time.sleep):
    """El puente activo o un NullBridge con el motivo. Nunca lanza."""
    environ = os.environ if environ is None else environ
    if not config.BRIDGE_ENABLED:
        return NullBridge("puente desactivado (config.BRIDGE_ENABLED = False)")
    if not netmode.is_online():
        return NullBridge("modo de red offline")
    try:
        guard = guard or CostGuard()
        provider = environ.get("IAF_BRIDGE_PROVIDER", "gemini")
        cfg = guard.provider(provider)
        model = environ.get("IAF_BRIDGE_MODEL") or (cfg.get("modelos_gratuitos") or [""])[0]
        key = environ.get(cfg.get("api_key_env") or "") or None
        guard.check_all(provider, model, key)
    except (CostGuardError, OSError, ValueError) as exc:
        return NullBridge(str(exc))
    except Exception as exc:  # noqa: BLE001 - sin YAML u otro fallo: desactivado
        return NullBridge(f"{type(exc).__name__}: {exc}")
    return OpenAICompatBridge(provider, cfg, model, key, guard, client, sleep)


def generate_sql(bridge, messages: list[dict]) -> tuple[str | None, str]:
    """(SQL extraída o None, motivo). No valida: quien llama aplica la validación de siempre."""
    import sql_engine as se
    try:
        res = bridge.chat(messages)
    except BridgeUnavailable as exc:
        return None, str(exc)
    sql = se.extract_sql(res.texto)
    return (sql or None), ("caché" if res.from_cache else "ok") if sql else "la respuesta no trae SQL"


def generar_negativas_api(por_necesidad: int = 3) -> list[dict]:
    """Pide a un modelo grande gratuito variantes de cada necesidad (modo online). Se valida al importar."""
    import sql_engine as se
    from business_queries import BUSINESS_QUERIES, render_sql
    from necesidades_negativas import importador

    bridge = get_bridge()
    if not bridge.available():
        raise BridgeUnavailable(getattr(bridge, "reason", "puente no disponible"))
    items: list[dict] = []
    for bq in BUSINESS_QUERIES:
        prompt = (
            f"Esquema de la base (SQLite):\n{se.get_schema_context()}\n\n"
            f"Necesidad {bq.id}: {bq.titulo}\nSQL verificada:\n{render_sql(bq).strip()}\n\n"
            f"Escribe {por_necesidad} variantes (parafrasis, filtro_distinto, agregado_distinto, "
            "casi_igual_trampa, ruido o ambigua) con su SQL SELECT de solo lectura. Responde SOLO un JSON: "
            f'[{{"necesidad_base": "{bq.id}", "tipo": "...", "pregunta": "...", "sql": "...", "notas": "..."}}]')
        res = bridge.chat([{"role": "user", "content": prompt}])
        try:
            items += importador.parse_pasted_json(res.texto)
        except ValueError:
            continue
    return items
