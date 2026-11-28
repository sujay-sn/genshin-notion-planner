"""Roster sync into Characters against the in-memory fake Notion. No network."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from fake_notion import FakeNotion
from gplanner.models import CharacterSnapshot, Talents, WeaponSnapshot
from gplanner.notion.props import decode, encode
from gplanner.notion.repo import apply_plan, fetch_pages, plan_roster
from gplanner.notion.schema import CHARACTERS

SYNC_1 = "2026-11-28T20:05:00+00:00"
SYNC_2 = "2026-11-29T20:05:00+00:00"


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def character(
    hoyo_id: int = 90000001, name: str = "Fixture A", **changes: Any
) -> CharacterSnapshot:
    snapshot = CharacterSnapshot(
        hoyo_id=hoyo_id,
        name=name,
        element="Pyro",
        weapon_type="Sword",
        rarity=5,
        level=80,
        ascension=5,
        ascension_ambiguous=True,
        constellation=1,
        talents=Talents(6, 8, 7),
        weapon=WeaponSnapshot(91000001, "Fixture Sword", 5, 80, 5, 1),
    )
    return dataclasses.replace(snapshot, **changes)


class NoSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def characters_db() -> tuple[FakeNotion, str]:
    fake = FakeNotion()
    return fake, fake.add_source("Characters", CHARACTERS.expected_types())


def sync(fake: FakeNotion, ds_id: str, roster: list[CharacterSnapshot], synced_at: str = SYNC_1):
    plan = plan_roster(roster, run(fetch_pages(fake, ds_id)), synced_at)
    run(apply_plan(fake, ds_id, plan, sleep=NoSleep()))
    return plan


def page_of(fake: FakeNotion, name: str) -> dict[str, Any]:
    return next(p for p in fake.pages_by_id.values() if decode(p["properties"]["Name"]) == name)


def value(fake: FakeNotion, name: str, prop: str) -> Any:
    return decode(page_of(fake, name)["properties"][prop])


def test_first_sync_creates_pages_with_script_owned_properties_only() -> None:
    fake, ds_id = characters_db()
    plan = sync(fake, ds_id, [character(), character(90000002, "Fixture B", level=90)])

    assert [w.name for w in plan.creates] == ["Fixture A", "Fixture B"]
    creates = [c[1] for c in fake.calls if c[0] == "pages.create"]
    assert all(c["parent"] == {"type": "data_source_id", "data_source_id": ds_id} for c in creates)
    for payload in creates:
        assert set(payload["properties"]) <= CHARACTERS.script_owned
    assert value(fake, "Fixture A", "Level") == 80
    assert value(fake, "Fixture A", "Rarity") == "5"
    assert value(fake, "Fixture A", "Weapon") == "Fixture Sword Lv80 R1"
    assert value(fake, "Fixture A", "Normal") == 6
    assert value(fake, "Fixture A", "Last synced") == SYNC_1


def test_second_sync_with_no_changes_makes_zero_writes() -> None:
    fake, ds_id = characters_db()
    roster = [character(), character(90000002, "Fixture B")]
    sync(fake, ds_id, roster)
    writes_before = len(fake.writes())

    plan = sync(fake, ds_id, roster, SYNC_2)

    assert plan.writes == ()
    assert plan.unchanged == 2
    assert len(fake.writes()) == writes_before
    # Last synced only moves when something changed.
    assert value(fake, "Fixture A", "Last synced") == SYNC_1


def test_a_change_updates_only_that_property_and_last_synced() -> None:
    fake, ds_id = characters_db()
    sync(fake, ds_id, [character()])

    plan = sync(fake, ds_id, [character(level=81, ascension=6, ascension_ambiguous=False)], SYNC_2)

    (update,) = plan.updates
    assert dict(update.changes) == {"Level": (80, 81), "Ascension": (5, 6)}
    (payload,) = [c[1] for c in fake.calls if c[0] == "pages.update"]
    assert set(payload["properties"]) == {"Level", "Ascension", "Last synced"}
    assert value(fake, "Fixture A", "Last synced") == SYNC_2


def test_your_properties_are_never_written_or_overwritten() -> None:
    fake, ds_id = characters_db()
    sync(fake, ds_id, [character()])
    page_id = page_of(fake, "Fixture A")["id"]
    yours = {
        "Building": encode("checkbox", True),
        "Priority": encode("number", 1),
        "Target level": encode("number", 90),
        "Target Skill": encode("number", 10),
    }
    for name, written in yours.items():
        fake.set_property(page_id, name, written)

    sync(fake, ds_id, [character(level=90, ascension=6, constellation=2)], SYNC_2)

    owned_by_you = set(CHARACTERS.properties) - CHARACTERS.script_owned
    for method, payload in fake.writes():
        assert not set(payload.get("properties", {})) & owned_by_you, method
    assert value(fake, "Fixture A", "Building") is True
    assert value(fake, "Fixture A", "Priority") == 1
    assert value(fake, "Fixture A", "Target Skill") == 10


def test_unknown_talents_leave_existing_levels_alone() -> None:
    fake, ds_id = characters_db()
    sync(fake, ds_id, [character()])

    plan = sync(fake, ds_id, [character(talents=None)], SYNC_2)

    assert plan.writes == ()
    assert value(fake, "Fixture A", "Skill") == 8


def test_a_new_character_without_talents_gets_no_talent_properties() -> None:
    fake, ds_id = characters_db()
    plan = sync(fake, ds_id, [character(talents=None)])
    assert not {"Normal", "Skill", "Burst"} & set(plan.creates[0].properties)


def test_writes_are_paced_under_notions_rate_limit() -> None:
    fake, ds_id = characters_db()
    roster = [character(90000000 + i, f"Fixture {i}") for i in range(4)]
    plan = plan_roster(roster, [], SYNC_1)
    sleep = NoSleep()
    run(apply_plan(fake, ds_id, plan, sleep=sleep))
    assert sleep.delays == [0.35, 0.35, 0.35]


def test_ticked_ascended_at_cap_away_from_a_cap_warns() -> None:
    fake, ds_id = characters_db()
    sync(fake, ds_id, [character()])
    fake.set_property(page_of(fake, "Fixture A")["id"], "Ascended at cap", encode("checkbox", True))

    at_cap = plan_roster([character()], run(fetch_pages(fake, ds_id)), SYNC_2)
    past_cap = plan_roster(
        [character(level=81, ascension=6, ascension_ambiguous=False)],
        run(fetch_pages(fake, ds_id)),
        SYNC_2,
    )

    assert at_cap.warnings == ()
    assert past_cap.warnings == (
        "Fixture A: 'Ascended at cap' is ticked but level 81 isn't a cap. "
        "Untick it so it doesn't count at the next cap.",
    )


def test_duplicate_pages_for_one_character_are_skipped_with_a_warning() -> None:
    fake, ds_id = characters_db()
    sync(fake, ds_id, [character()])
    duplicate = plan_roster([character()], [], SYNC_1).creates[0]
    run(
        fake.pages.create(
            parent={"type": "data_source_id", "data_source_id": ds_id},
            properties=dict(duplicate.properties),
        )
    )

    plan = plan_roster([character(level=90)], run(fetch_pages(fake, ds_id)), SYNC_2)

    assert plan.writes == ()
    assert plan.warnings[0].startswith("Fixture A: 2 Characters pages have HoYo ID 90000001")


def test_pages_not_on_the_account_are_left_alone_with_a_warning() -> None:
    fake, ds_id = characters_db()
    sync(fake, ds_id, [character(), character(90000002, "Fixture B")])

    plan = plan_roster([character()], run(fetch_pages(fake, ds_id)), SYNC_2)

    assert plan.writes == ()
    assert plan.warnings == ("Fixture B: in Characters but not on the account. Left as it is.",)


def test_pages_without_a_hoyo_id_are_ignored() -> None:
    fake, ds_id = characters_db()
    run(
        fake.pages.create(
            parent={"type": "data_source_id", "data_source_id": ds_id},
            properties={"Name": encode("title", "My notes row")},
        )
    )
    plan = plan_roster([character()], run(fetch_pages(fake, ds_id)), SYNC_1)
    assert [w.name for w in plan.creates] == ["Fixture A"]
    assert plan.warnings == ()
