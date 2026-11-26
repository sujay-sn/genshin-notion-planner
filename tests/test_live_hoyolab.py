"""One-off live check against the real HoYoLAB account in .env.

Skipped by default. Run it on purpose with output shown:

    pytest -m live -s tests/test_live_hoyolab.py

It makes about five read-only requests. It never prints cookies or the UID.
Besides checking that the roster comes back, it prints what M1 couldn't settle
offline (DESIGN.md section 15):

1. Whether the raw character data has an ascension field genshin.py drops.
2. The talent order for characters with an alternate sprint.
3. Whether character detail talent levels include constellation bonuses.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from gplanner.cli import format_roster
from gplanner.config import Settings
from gplanner.hoyolab.client import HoyolabClient, HoyolabError

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def client() -> HoyolabClient:
    settings = Settings.load()
    if not (settings.hoyolab_ltuid_v2 and settings.hoyolab_ltoken_v2 and settings.genshin_uid):
        pytest.skip("HoYoLAB cookies or GENSHIN_UID not set in .env")
    return HoyolabClient.from_settings(settings)


def test_live_roster_and_open_questions(client: HoyolabClient) -> None:
    asyncio.run(_check(client))


async def _check(client: HoyolabClient) -> None:
    roster = await client.fetch_roster()
    assert roster.characters, "HoYoLAB returned no characters"
    print("\n" + format_roster(roster))
    for warning in roster.warnings:
        print(f"warning: {warning}")

    # Raw data, read directly from genshin.py for diagnostics only. Key names are
    # printed, plus the values of any key that looks like an ascension field.
    raw: Any = await client._api.get_genshin_detailed_characters(client.uid, return_raw_data=True)
    first = raw["list"][0]
    print("\n[1] Raw character keys:", sorted(first))
    print("    Raw base keys:", sorted(first["base"]))
    hints = ("promote", "break", "ascen")
    for entry in raw["list"][:5]:
        found = {k: v for k, v in entry["base"].items() if any(h in k.lower() for h in hints)}
        print(
            f"    {entry['base'].get('name')}: level {entry['base'].get('level')}, {found or '-'}"
        )

    print("\n[2] Characters with more than three levelable talents (skill_type 1):")
    for entry in raw["list"]:
        active = [s for s in entry["skills"] if s.get("skill_type") == 1]
        if len(active) > 3:
            names = [f"{s['name']} (Lv{s['level']})" for s in active]
            print(f"    {entry['base']['name']}: {names}")
    skill_types = sorted({s.get("skill_type") for e in raw["list"] for s in e["skills"]})
    print("    skill_type values seen:", skill_types)

    print("\n[3] Character detail vs calculator talent levels:")
    candidates = sorted(
        (c for c in roster.characters if c.talents and c.constellation >= 3),
        key=lambda c: -c.constellation,
    )
    if not candidates:
        print("    No C3+ character with talents to compare.")
        return
    pick = candidates[0]
    try:
        base = await client.fetch_base_talents(pick.hoyo_id)
    except HoyolabError as exc:
        print(f"    Skipped: {exc}")
        return
    print(f"    {pick.name} C{pick.constellation}")
    print(f"    character detail: {pick.talents}")
    print(f"    calculator:       {base}")
    print("    Same numbers mean detail levels are base levels; +3 means bonuses are included.")
