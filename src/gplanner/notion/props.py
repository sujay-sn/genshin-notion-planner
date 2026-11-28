"""Converting between Python values and Notion page property values.

Pure functions, no requests. ``encode`` builds what a page create or update
sends. ``decode`` reads what a query returns back into the same Python value,
so the two can be compared to decide whether a write is needed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from gplanner.notion.client import plain_text


def _text(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": value}}] if value else []


def encode(prop_type: str, value: Any) -> dict[str, Any]:
    """The page property value for ``value`` in a property of ``prop_type``."""
    if prop_type == "title":
        return {"title": _text(value or "")}
    if prop_type == "rich_text":
        return {"rich_text": _text(value or "")}
    if prop_type == "number":
        return {"number": value}
    if prop_type == "select":
        return {"select": {"name": value} if value else None}
    if prop_type == "multi_select":
        return {"multi_select": [{"name": name} for name in value or ()]}
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    if prop_type == "date":
        return {"date": {"start": value} if value else None}
    if prop_type == "url":
        return {"url": value or None}
    raise ValueError(f"Can't write a {prop_type} property")


def decode(prop: dict[str, Any]) -> Any:
    """The Python value of a page property as a query returns it."""
    prop_type = prop["type"]
    value = prop.get(prop_type)
    if prop_type in ("title", "rich_text"):
        return plain_text(value or [])
    if prop_type in ("number", "checkbox", "url"):
        return value
    if prop_type == "select":
        return value["name"] if value else None
    if prop_type == "multi_select":
        return tuple(sorted(option["name"] for option in value or ()))
    if prop_type == "date":
        return value["start"] if value else None
    raise ValueError(f"Can't read a {prop_type} property")


def normalize(prop_type: str, value: Any) -> Any:
    """The form ``decode`` would return for ``value``, for comparing."""
    if prop_type in ("title", "rich_text"):
        return value or ""
    if prop_type in ("select", "date", "url"):
        return value or None
    if prop_type == "multi_select":
        return tuple(sorted(value or ()))
    if prop_type == "checkbox":
        return bool(value)
    return value


def page_values(page: dict[str, Any], names: Sequence[str]) -> dict[str, Any]:
    """Decoded values of the named properties on a queried page."""
    properties = page["properties"]
    return {name: decode(properties[name]) for name in names if name in properties}
