"""Shared test setup.

Blocks all socket creation unless a test is marked ``live``, so the default
test run is guaranteed not to touch the network.
"""

from __future__ import annotations

import socket

import pytest


class NetworkBlockedError(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live"):
        return

    def guard(*args: object, **kwargs: object) -> None:
        raise NetworkBlockedError("Network access in a non-live test. Mark it @pytest.mark.live.")

    monkeypatch.setattr(socket, "socket", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
