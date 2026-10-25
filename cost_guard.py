"""Guardián de costo (fase 11): garantiza que el puente a un modelo grande nunca cueste dinero.

Qué hace, en orden, antes de cada petición de red:
  1. Allowlist: el proveedor debe estar en bridge_providers.yaml con `enabled: true`.
  2. Modelo: debe estar en `modelos_gratuitos` del proveedor (y, en OpenRouter, terminar en ":free").
  3. Llave: no puede parecer de facturación (llaves_prohibidas) y debe tener el prefijo del proveedor.
  4. Interruptor: si una respuesta anterior mostró un posible cobro, queda bloqueado hasta `reset()`.
  5. Cuota local por minuto y por día (contador persistente en .cache/), por debajo del límite gratuito.
Además guarda una caché en disco por hash (proveedor+modelo+mensajes): una consulta idéntica nunca se
repite en red. Si algo falla, se lanza CostGuardError/QuotaExceeded y quien llama degrada a offline.
"""

from __future__ import annotations

import json
import time
from hashlib import sha256
from pathlib import Path

import config


class CostGuardError(RuntimeError):
    """El guardián rechazó la petición (proveedor, modelo o llave fuera de la política de costo cero)."""


class QuotaExceeded(CostGuardError):
    """Se alcanzó el tope local de peticiones (por minuto o por día)."""


def load_providers(path: Path | None = None) -> dict:
    import yaml
    data = yaml.safe_load(Path(path or config.BRIDGE_PROVIDERS_PATH).read_text(encoding="utf-8")) or {}
    return data


class CostGuard:
    def __init__(self, providers: dict | None = None, cache_dir: Path | None = None,
                 max_per_minute: int | None = None, max_per_day: int | None = None, now=time.time):
        self.cfg = providers if providers is not None else load_providers()
        self.cache_dir = Path(cache_dir or config.CACHE_DIR)
        self.max_per_minute = config.BRIDGE_MAX_PER_MINUTE if max_per_minute is None else max_per_minute
        self.max_per_day = config.BRIDGE_MAX_PER_DAY if max_per_day is None else max_per_day
        self.now = now
        self.state_path = self.cache_dir / "cost_guard.json"
        self.responses_dir = self.cache_dir / "bridge_cache"

    # --- política ---------------------------------------------------------------------
    def provider(self, name: str) -> dict:
        prov = (self.cfg.get("proveedores") or {}).get(name)
        if prov is None:
            raise CostGuardError(f"Proveedor '{name}' fuera de la allowlist (bridge_providers.yaml).")
        if not prov.get("enabled"):
            raise CostGuardError(f"Proveedor '{name}' deshabilitado: no se pudo verificar su capa gratuita.")
        return prov

    def check_model(self, name: str, model: str) -> None:
        prov = self.provider(name)
        suffix = prov.get("require_model_suffix")
        if suffix and not str(model).endswith(suffix):
            raise CostGuardError(f"Modelo '{model}' rechazado: en {name} solo se permiten modelos '{suffix}'.")
        if model not in (prov.get("modelos_gratuitos") or []):
            raise CostGuardError(f"Modelo '{model}' no está en modelos_gratuitos de {name}.")

    def check_key(self, name: str, key: str | None) -> None:
        prov = self.provider(name)
        if prov.get("local"):
            return
        if not key:
            raise CostGuardError(f"Falta la llave en la variable {prov.get('api_key_env')}.")
        for bad in self.cfg.get("llaves_prohibidas") or []:
            if key.startswith(bad):
                raise CostGuardError("La llave parece de un servicio de pago o de facturación: rechazada.")
        prefix = prov.get("key_prefix") or ""
        if prefix and not key.startswith(prefix):
            raise CostGuardError(f"La llave no tiene el formato de {name} (debe empezar con '{prefix}').")

    def check_all(self, name: str, model: str, key: str | None) -> None:
        self.check_model(name, model)
        self.check_key(name, key)
        tripped = self._state().get("tripped")
        if tripped:
            raise CostGuardError(f"Puente bloqueado por seguridad: {tripped}. Revisa tu cuenta y usa reset().")

    # --- cuota persistente ------------------------------------------------------------
    def _state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, state: dict) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            pass

    def acquire(self, name: str) -> None:
        """Cuenta una petición o lanza QuotaExceeded."""
        state, now = self._state(), self.now()
        calls = state.setdefault("calls", {}).setdefault(name, [])
        calls[:] = [t for t in calls if now - t < 86400]
        if len(calls) >= self.max_per_day:
            raise QuotaExceeded(f"Tope diario local alcanzado ({self.max_per_day} peticiones a {name}).")
        if sum(now - t < 60 for t in calls) >= self.max_per_minute:
            raise QuotaExceeded(f"Tope por minuto local alcanzado ({self.max_per_minute} peticiones a {name}).")
        calls.append(now)
        self._save(state)

    def used_today(self, name: str) -> int:
        now = self.now()
        return sum(now - t < 86400 for t in self._state().get("calls", {}).get(name, []))

    # --- interruptor por posible cobro -----------------------------------------------
    def note_response(self, status: int, data: dict | None) -> None:
        """Detecta señales de cobro (402, usage.cost > 0, mensajes de billing) y bloquea el puente."""
        reason = None
        if status == 402:
            reason = "el proveedor respondió 402 (pago requerido)"
        elif isinstance(data, dict):
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            cost = usage.get("cost")
            if isinstance(cost, (int, float)) and cost > 0:
                reason = f"la respuesta reporta un costo de {cost}"
            text = json.dumps(data.get("error", ""), ensure_ascii=False).lower() if data.get("error") else ""
            if any(w in text for w in ("billing", "insufficient credit", "payment required", "add credits")):
                reason = "el proveedor menciona facturación o créditos"
        if reason:
            state = self._state()
            state["tripped"] = reason
            self._save(state)
            raise CostGuardError(f"Posible cobro detectado ({reason}). Puente bloqueado.")

    def reset(self) -> None:
        state = self._state()
        state.pop("tripped", None)
        self._save(state)

    # --- caché en disco ---------------------------------------------------------------
    @staticmethod
    def cache_key(provider: str, model: str, messages: list[dict]) -> str:
        body = json.dumps([provider, model, messages], ensure_ascii=False, sort_keys=True)
        return sha256(body.encode("utf-8")).hexdigest()

    def cache_get(self, key: str) -> str | None:
        try:
            return json.loads((self.responses_dir / f"{key}.json").read_text(encoding="utf-8"))["texto"]
        except (OSError, ValueError, KeyError):
            return None

    def cache_put(self, key: str, text: str) -> None:
        try:
            self.responses_dir.mkdir(parents=True, exist_ok=True)
            (self.responses_dir / f"{key}.json").write_text(
                json.dumps({"texto": text}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
