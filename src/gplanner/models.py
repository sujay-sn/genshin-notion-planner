"""The project's own data models.

``hoyolab/`` turns genshin.py objects into these, and everything downstream
(``planner/``, ``notion/``, the CLI) works only with these. That keeps a
genshin.py change inside one folder (DESIGN.md section 3).
"""

from __future__ import annotations

from dataclasses import dataclass

# Character level caps before each ascension: ascension N lifts the cap from
# ASCENSION_CAPS[N - 1] to the next one. Ascension 6 is the last.
ASCENSION_CAPS: tuple[int, ...] = (20, 40, 50, 60, 70, 80)
MAX_ASCENSION = len(ASCENSION_CAPS)


def ascension_for_level(level: int) -> tuple[int, bool]:
    """Lowest ascension consistent with ``level``, and whether it's ambiguous.

    HoYoLAB doesn't report a character's ascension, only their level. Between
    caps the level settles it. At a cap (20, 40, ..., 80) the character may or
    may not have ascended yet, so the lower value is returned and flagged.
    """
    if level < 1:
        raise ValueError(f"level must be at least 1, got {level}")
    below = sum(1 for cap in ASCENSION_CAPS if cap < level)
    return below, level in ASCENSION_CAPS


@dataclass(frozen=True)
class WeaponSnapshot:
    hoyo_id: int
    name: str
    rarity: int
    level: int
    ascension: int
    refinement: int

    @property
    def label(self) -> str:
        """How the weapon reads in the roster table and Notion, e.g. "Amos' Bow Lv90 R1"."""
        return f"{self.name} Lv{self.level} R{self.refinement}"


@dataclass(frozen=True)
class Talents:
    """Base talent levels, without constellation bonuses (DESIGN.md section 6.1)."""

    normal: int
    skill: int
    burst: int


@dataclass(frozen=True)
class CharacterSnapshot:
    """One owned character as fetched from HoYoLAB."""

    hoyo_id: int
    name: str
    element: str
    weapon_type: str
    rarity: int
    level: int
    ascension: int
    ascension_ambiguous: bool
    constellation: int
    talents: Talents | None
    weapon: WeaponSnapshot


@dataclass(frozen=True)
class RosterResult:
    """A fetched roster plus anything that didn't normalize cleanly."""

    characters: tuple[CharacterSnapshot, ...]
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
