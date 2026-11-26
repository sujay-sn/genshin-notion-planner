"""Shared test setup.

Blocks outbound network access unless a test is marked ``live``, so the
default test run is guaranteed not to touch the network.

Loopback stays allowed: asyncio's event loop on Windows builds its internal
socket pair over 127.0.0.1, so blocking socket creation outright would break
every async test. Anything else fails at DNS lookup or connect.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import pytest

_LOOPBACK = {"localhost", "127.0.0.1", "::1", None}


class NetworkBlockedError(RuntimeError):
    pass


def _refuse(target: object) -> None:
    raise NetworkBlockedError(
        f"Network access to {target!r} in a non-live test. Mark it @pytest.mark.live."
    )


def _host_of(address: object) -> object:
    # AF_INET/AF_INET6 addresses are tuples; AF_UNIX paths are local.
    return address[0] if isinstance(address, tuple) else None


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live"):
        return

    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = asyncio.BaseEventLoop.create_connection

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(host, bytes):
            host = host.decode()
        if host not in _LOOPBACK:
            _refuse(host)
        return real_getaddrinfo(host, *args, **kwargs)

    def connect(self: socket.socket, address: Any) -> Any:
        if _host_of(address) not in _LOOPBACK:
            _refuse(address)
        return real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> Any:
        if _host_of(address) not in _LOOPBACK:
            _refuse(address)
        return real_connect_ex(self, address)

    async def create_connection(
        self: asyncio.BaseEventLoop,
        protocol_factory: Any,
        host: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        # Catches IP literals, which asyncio connects to without a DNS lookup.
        if host not in _LOOPBACK:
            _refuse(host)
        return await real_create_connection(self, protocol_factory, host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(asyncio.BaseEventLoop, "create_connection", create_connection)

    # aiohttp connects with loop.sock_connect (happy eyeballs), which goes
    # straight to the OS without socket.connect on the Windows proactor loop.
    for loop_cls in _event_loop_classes():
        monkeypatch.setattr(loop_cls, "sock_connect", _guarded_sock_connect(loop_cls.sock_connect))


def _event_loop_classes() -> list[type]:
    from asyncio import selector_events

    classes: list[type] = [selector_events.BaseSelectorEventLoop]
    try:
        from asyncio import proactor_events
    except ImportError:  # pragma: no cover - not on every platform
        return classes
    classes.append(proactor_events.BaseProactorEventLoop)
    return classes


def _guarded_sock_connect(real: Any) -> Any:
    async def sock_connect(self: Any, sock: socket.socket, address: Any) -> Any:
        if _host_of(address) not in _LOOPBACK:
            _refuse(address)
        return await real(self, sock, address)

    return sock_connect
