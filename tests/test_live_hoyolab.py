"""One-off live check against the real HoYoLAB account in .env.

Skipped by default. Run it on purpose with output shown:

    pytest -m live -s tests/test_live_hoyolab.py

It makes read-only requests: the roster (2), the raw character data again
(2), and one calculator request per C3+ character. It never prints cookies
or the UID. Besides checking that the roster comes back, it settles DESIGN.md
open question 9: does taking C3/C5 bonuses off by effect text give the same
base levels as the calculator?
"""

from __future__ import annotations

import asyncio

import pytest

from gplanner.cli import format_roster
from gplanner.config import Settings
from gplanner.hoyolab.client import HoyolabClient, HoyolabError, base_talents_from_detail
from gplanner.models import Talents

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def client() -> HoyolabClient:
    settings = Settings.load()
    if not (settings.hoyolab_ltuid_v2 and settings.hoyolab_ltoken_v2 and settings.genshin_uid):
        pytest.skip("HoYoLAB cookies or GENSHIN_UID not set in .env")
    return HoyolabClient.from_settings(settings)


def test_live_roster_and_bonus_removal(client: HoyolabClient) -> None:
    asyncio.run(_check(client))


async def _check(client: HoyolabClient) -> None:
    roster = await client.fetch_roster()
    assert roster.characters, "HoYoLAB returned no characters"
    print("\n" + format_roster(roster))
    for note in roster.notes:
        print(f"note: {note}")
    for warning in roster.warnings:
        print(f"warning: {warning}")

    # Read the parsed detail directly for diagnostics, so the effect-text method
    # can be compared with the calculator for every character it applies to.
    detail = await client._api.get_genshin_detailed_characters(client.uid)
    boosted = [c for c in detail.characters if c.constellation >= 3]
    print(f"\n[Q9] Effect text vs calculator for {len(boosted)} C3+ characters:")

    mismatches: list[str] = []
    for raw in sorted(boosted, key=lambda c: c.name):
        derived, reason = base_talents_from_detail(raw)
        try:
            calculator = await client.fetch_base_talents(raw.id)
        except HoyolabError as exc:
            print(f"    {raw.name} C{raw.constellation}: calculator failed ({exc})")
            continue
        if derived is None:
            print(f"    {raw.name} C{raw.constellation}: no effect-text result ({reason})")
            continue
        same = derived == calculator
        mark = "same" if same else "DIFFERENT"
        print(f"    {raw.name} C{raw.constellation}: {_fmt(derived)} vs {_fmt(calculator)} {mark}")
        if not same:
            mismatches.append(raw.name)

    assert not mismatches, f"Effect-text base levels differ from the calculator: {mismatches}"


def _fmt(talents: Talents) -> str:
    return f"{talents.normal}/{talents.skill}/{talents.burst}"
