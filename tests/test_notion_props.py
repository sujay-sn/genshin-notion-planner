from __future__ import annotations

from typing import Any

import pytest

from fake_notion import _to_read
from gplanner.notion.props import decode, encode, normalize


@pytest.mark.parametrize(
    ("prop_type", "value"),
    [
        ("title", "Raiden Shogun"),
        ("rich_text", "Amos' Bow Lv90 R1"),
        ("number", 90),
        ("select", "Electro"),
        ("multi_select", ("Monday", "Thursday")),
        ("checkbox", True),
        ("date", "2026-11-28T20:05:00+00:00"),
        ("url", "https://example.invalid/route"),
    ],
)
def test_encode_then_decode_round_trips(prop_type: str, value: Any) -> None:
    written = encode(prop_type, value)
    assert decode(_to_read(prop_type, written[prop_type])) == normalize(prop_type, value)


@pytest.mark.parametrize(
    ("prop_type", "written"),
    [
        ("title", {"title": []}),
        ("rich_text", {"rich_text": []}),
        ("select", {"select": None}),
        ("date", {"date": None}),
        ("url", {"url": None}),
    ],
)
def test_blank_values_encode_as_clears(prop_type: str, written: dict[str, Any]) -> None:
    assert encode(prop_type, None) == written


def test_blank_and_empty_compare_equal() -> None:
    assert normalize("rich_text", None) == normalize("rich_text", "")
    assert normalize("select", "") == normalize("select", None)


def test_unsupported_types_are_refused() -> None:
    with pytest.raises(ValueError):
        encode("formula", 1)
    with pytest.raises(ValueError):
        decode({"type": "rollup", "rollup": {}})
