"""Modo de red (fase 11): "offline" (por defecto) u "online".

En `offline` el código no abre ningún socket hacia fuera: solo se permite localhost (Ollama). Todo
acceso a red de la aplicación pasa por `require_online()`, que lanza OfflineError en ese modo. Para
poder DEMOSTRAR el cero tráfico externo hay además `block_external_sockets()`, que intercepta
`socket` y registra (y bloquea) cualquier intento de conexión a una dirección que no sea local; lo usan
las pruebas y la evaluación con `--red offline`.
"""

from __future__ import annotations

import ipaddress
import socket
from contextlib import contextmanager

import config

MODOS = ("offline", "online")


class OfflineError(RuntimeError):
    """Se intentó usar la red estando en modo offline."""


def get_mode() -> str:
    mode = str(getattr(config, "MODO_RED", "offline")).strip().lower()
    return mode if mode in MODOS else "offline"     # cualquier valor raro = el más conservador


def set_mode(mode: str) -> None:
    if mode not in MODOS:
        raise ValueError(f"modo de red inválido: {mode!r} (opciones: {', '.join(MODOS)})")
    config.MODO_RED = mode


def is_online() -> bool:
    return get_mode() == "online"


def require_online(accion: str = "acceder a la red") -> None:
    if not is_online():
        raise OfflineError(f"Modo offline: no se permite {accion}. Activa el modo online "
                           "(IAF_MODO_RED=online) solo si quieres usar el puente a un modelo grande gratuito.")


def is_local_host(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    host = str(host or "").strip().strip("[]").lower()
    if host in ("", "localhost", "localhost.localdomain", "::1", "0.0.0.0"):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


@contextmanager
def block_external_sockets(attempts: list | None = None):
    """Bloquea y registra las conexiones no locales mientras dura el bloque.

    `attempts` (lista) recibe cada destino externo intentado. Las conexiones a localhost y a
    sockets locales (AF_UNIX) pasan intactas.
    """
    attempts = attempts if attempts is not None else []
    orig_connect, orig_connect_ex = socket.socket.connect, socket.socket.connect_ex
    orig_getaddrinfo = socket.getaddrinfo

    def check(address):
        if isinstance(address, tuple) and address and not is_local_host(address[0]):
            attempts.append(address)
            raise OfflineError(f"conexión externa bloqueada en modo offline: {address[0]}")

    def connect(self, address):
        check(address)
        return orig_connect(self, address)

    def connect_ex(self, address):
        check(address)
        return orig_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if host is not None and not is_local_host(host):
            attempts.append((host, args[0] if args else None))
            raise OfflineError(f"resolución DNS externa bloqueada en modo offline: {host}")
        return orig_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, getaddrinfo
    try:
        yield attempts
    finally:
        socket.socket.connect, socket.socket.connect_ex = orig_connect, orig_connect_ex
        socket.getaddrinfo = orig_getaddrinfo
