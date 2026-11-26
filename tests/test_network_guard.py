"""The conftest guard still blocks outbound network access in non-live tests."""

from __future__ import annotations

import asyncio
import socket

import aiohttp
import pytest

from conftest import NetworkBlockedError


def test_dns_lookup_is_blocked() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("example.com", 80), timeout=1)


def test_connect_to_ip_literal_is_blocked() -> None:
    with socket.socket() as sock, pytest.raises(NetworkBlockedError):
        sock.connect(("192.0.2.1", 80))


def test_aiohttp_request_is_blocked() -> None:
    async def fetch() -> None:
        async with aiohttp.ClientSession() as session:
            await session.get("http://192.0.2.1/")

    with pytest.raises((NetworkBlockedError, aiohttp.ClientError)) as info:
        asyncio.run(fetch())
    # aiohttp may wrap the error; either way it must come from the guard.
    assert "non-live test" in str(info.value) or isinstance(info.value, NetworkBlockedError)


def test_event_loop_still_runs() -> None:
    async def answer() -> int:
        await asyncio.sleep(0)
        return 42

    assert asyncio.run(answer()) == 42
