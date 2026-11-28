"""Roster sync into the Characters database.

``plan_roster`` is pure: given the HoYoLAB roster and the pages already in
Notion, it works out which pages to create or update and which properties
changed. ``apply_plan`` makes the writes. Only script-owned properties are
ever compared or written (DESIGN.md section 6.2), and a page is written only
when one of them changed, so a second run makes no writes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from notion_client import AsyncClient
from notion_client.helpers import async_collect_paginated_api

from gplanner.models import ASCENSION_CAPS, CharacterSnapshot
from gplanner.notion.client import call
from gplanner.notion.props import encode, normalize, page_values
from gplanner.notion.schema import CHARACTERS

KEY = "HoYo ID"
LAST_SYNCED = "Last synced"
ASCENDED_AT_CAP = "Ascended at cap"

# Notion's limit is about three requests a second on average (DESIGN.md section 2).
WRITE_INTERVAL_SECONDS = 0.35


def character_values(c: CharacterSnapshot) -> dict[str, Any]:
    """Script-owned Characters values for one character, except Last synced.

    Talents are left out when they're unknown, so a failed lookup never
    blanks levels already in Notion.
    """
    values: dict[str, Any] = {
        "Name": c.name,
        KEY: c.hoyo_id,
        "Element": c.element,
        "Weapon type": c.weapon_type,
        "Rarity": str(c.rarity),
        "Level": c.level,
        "Ascension": c.ascension,
        "Constellation": c.constellation,
        "Weapon": c.weapon.label,
    }
    if c.talents is not None:
        values.update(Normal=c.talents.normal, Skill=c.talents.skill, Burst=c.talents.burst)
    return values


@dataclass(frozen=True)
class RowWrite:
    name: str
    page_id: str | None  # None means create
    # property -> (old, new). For a create, old is None.
    changes: Mapping[str, tuple[Any, Any]]
    properties: Mapping[str, Any]  # encoded payload, script-owned properties only


@dataclass(frozen=True)
class RosterPlan:
    creates: tuple[RowWrite, ...] = ()
    updates: tuple[RowWrite, ...] = ()
    unchanged: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def writes(self) -> tuple[RowWrite, ...]:
        return self.creates + self.updates


def _encode_all(values: Mapping[str, Any]) -> dict[str, Any]:
    return {name: encode(CHARACTERS.property_type(name), v) for name, v in values.items()}


def plan_roster(
    roster: Sequence[CharacterSnapshot],
    pages: Sequence[dict[str, Any]],
    synced_at: str,
) -> RosterPlan:
    """What to write to Characters so it matches ``roster``.

    ``synced_at`` is the ISO timestamp written to Last synced on every page
    that's created or changed, and only on those.
    """
    warnings: list[str] = []
    compared = sorted(CHARACTERS.script_owned - {LAST_SYNCED})

    by_key: dict[int, list[dict[str, Any]]] = {}
    for page in pages:
        key = page_values(page, [KEY]).get(KEY)
        if key is not None:
            by_key.setdefault(int(key), []).append(page)

    creates: list[RowWrite] = []
    updates: list[RowWrite] = []
    unchanged = 0
    roster_keys = set()

    for character in roster:
        roster_keys.add(character.hoyo_id)
        desired = character_values(character)
        matches = by_key.get(character.hoyo_id, [])

        if len(matches) > 1:
            warnings.append(
                f"{character.name}: {len(matches)} Characters pages have HoYo ID "
                f"{character.hoyo_id}. Delete the extra ones; this character was skipped."
            )
            continue

        if not matches:
            values = {**desired, LAST_SYNCED: synced_at}
            creates.append(
                RowWrite(
                    name=character.name,
                    page_id=None,
                    changes={name: (None, v) for name, v in values.items()},
                    properties=_encode_all(values),
                )
            )
            continue

        page = matches[0]
        current = page_values(page, [*compared, ASCENDED_AT_CAP])
        if current.get(ASCENDED_AT_CAP) and character.level not in ASCENSION_CAPS:
            warnings.append(
                f"{character.name}: 'Ascended at cap' is ticked but level {character.level} "
                "isn't a cap. Untick it so it doesn't count at the next cap."
            )

        changes = {}
        for name, new in desired.items():
            prop_type = CHARACTERS.property_type(name)
            old = current.get(name)
            if normalize(prop_type, old) != normalize(prop_type, new):
                changes[name] = (old, new)
        if not changes:
            unchanged += 1
            continue
        values = {name: new for name, (_, new) in changes.items()}
        values[LAST_SYNCED] = synced_at
        updates.append(
            RowWrite(
                name=character.name,
                page_id=page["id"],
                changes=changes,
                properties=_encode_all(values),
            )
        )

    for key, extra in by_key.items():
        if key not in roster_keys:
            name = page_values(extra[0], ["Name"]).get("Name") or f"HoYo ID {key}"
            warnings.append(f"{name}: in Characters but not on the account. Left as it is.")

    return RosterPlan(tuple(creates), tuple(updates), unchanged, tuple(warnings))


async def fetch_pages(notion: AsyncClient, ds_id: str) -> list[dict[str, Any]]:
    return await call(
        "Read Characters",
        async_collect_paginated_api(notion.data_sources.query, data_source_id=ds_id),
    )


async def apply_plan(
    notion: AsyncClient,
    ds_id: str,
    plan: RosterPlan,
    *,
    sleep: Callable[[float], Awaitable[Any]],
    interval: float = WRITE_INTERVAL_SECONDS,
) -> None:
    """Make the plan's writes one at a time, paced under Notion's rate limit."""
    for index, write in enumerate(plan.writes):
        if index:
            await sleep(interval)
        if write.page_id is None:
            await call(
                f"Create {write.name}",
                notion.pages.create(
                    parent={"type": "data_source_id", "data_source_id": ds_id},
                    properties=dict(write.properties),
                ),
            )
        else:
            await call(
                f"Update {write.name}",
                notion.pages.update(page_id=write.page_id, properties=dict(write.properties)),
            )
