from __future__ import annotations

import pytest

from gplanner.models import ascension_for_level


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (1, (0, False)),
        (19, (0, False)),
        (20, (0, True)),
        (21, (1, False)),
        (40, (1, True)),
        (41, (2, False)),
        (50, (2, True)),
        (60, (3, True)),
        (70, (4, True)),
        (79, (5, False)),
        (80, (5, True)),
        (81, (6, False)),
        (90, (6, False)),
    ],
)
def test_ascension_for_level(level: int, expected: tuple[int, bool]) -> None:
    assert ascension_for_level(level) == expected


def test_ascension_rejects_level_zero() -> None:
    with pytest.raises(ValueError):
        ascension_for_level(0)
