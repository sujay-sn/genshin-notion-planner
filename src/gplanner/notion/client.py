"""Notion client setup and error mapping.

This folder is the only place that talks to Notion (DESIGN.md section 3).
notion-client 3.1.0 speaks API version 2025-09-03 and already retries 429s
using Notion's Retry-After header (DESIGN.md section 11), so nothing here
re-implements that.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, TypeVar

from notion_client import AsyncClient
from notion_client.errors import NotionClientErrorBase

from gplanner.config import ConfigError, Settings

T = TypeVar("T")


class NotionError(Exception):
    """A Notion step failed. The message is safe to print: it never holds the token."""


class NotionSchemaError(NotionError):
    """A database is missing a property the script needs, or it has the wrong type."""


def make_client(settings: Settings) -> AsyncClient:
    if not settings.notion_token:
        raise ConfigError("Missing in .env: NOTION_TOKEN")
    return AsyncClient(auth=settings.notion_token)


async def call(step: str, request: Awaitable[T]) -> T:
    """Await one Notion request, turning library errors into ``NotionError``."""
    try:
        return await request
    except NotionClientErrorBase as exc:
        raise NotionError(f"{step}: {exc}") from None


def plain_text(rich_text: list[dict[str, Any]]) -> str:
    return "".join(part.get("plain_text", "") for part in rich_text)
