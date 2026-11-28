"""HoyolabClient against a fake genshin.py client. No network.

The fixture is synthetic: made-up IDs and names in the shape of HoYoLAB's
``character/detail`` response, parsed by genshin.py's real models.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiohttp
import genshin
import pytest

from gplanner.config import ConfigError, Settings
from gplanner.hoyolab.client import (
    HoyolabAuthError,
    HoyolabCaptchaError,
    HoyolabClient,
    HoyolabError,
    HoyolabUnavailableError,
    base_talents_from_detail,
)
from gplanner.models import Talents

FIXTURES = Path(__file__).parent / "fixtures"


def detail_characters() -> genshin.models.GenshinDetailCharacters:
    raw = json.loads((FIXTURES / "character_detail.json").read_text(encoding="utf-8"))
    return genshin.models.GenshinDetailCharacters(**raw)


# Calculator talents as (id, group_id, level). genshin.py reads the type from
# group_id: a middle digit of 2 is a passive, otherwise the last digit is
# 1 attack, 2 skill, 3 sprint, 9 burst.
ATTACK, SKILL, SPRINT, BURST = (
    (10001, 4131, 6),
    (10002, 4132, 8),
    (10003, 4133, 1),
    (10004, 4139, 10),
)
PASSIVES = [(10005, 4121, 1), (10006, 4122, 1)]


def calculator_details(
    talents: list[tuple[int, int, int]],
) -> genshin.models.CalculatorCharacterDetails:
    return genshin.models.CalculatorCharacterDetails(
        weapon={
            "id": 1,
            "name": "W",
            "icon": "https://example.invalid/w.png",
            "weapon_level": 4,
            "weapon_cat_id": 1,
            "level_current": 90,
            "max_level": 90,
        },
        skill_list=[
            {
                "id": tid,
                "group_id": group_id,
                "name": f"Talent {group_id}",
                "icon": "https://example.invalid/t.png",
                "level_current": level,
                "max_level": 10,
            }
            for tid, group_id, level in talents
        ],
        reliquary_list=[],
    )


class FakeApi:
    """Returns or raises the queued results, one per call."""

    def __init__(self, *results: Any) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, Any]] = []

    def _next(self) -> Any:
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    async def get_genshin_detailed_characters(self, uid: int | None = None) -> Any:
        self.calls.append(("detail", uid))
        return self._next()

    async def get_character_details(self, character: int, *, uid: int | None = None) -> Any:
        self.calls.append(("calculator", character))
        return self._next()


class RecordingSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def make_client(api: FakeApi, sleep: RecordingSleep | None = None) -> HoyolabClient:
    return HoyolabClient(api, uid=800000000, sleep=sleep or RecordingSleep())


def run(coro: Any) -> Any:
    return asyncio.run(coro)


# Roster normalization
#
# Fixture characters:
#   90000001  C0, three talents, nothing to take off
#   90000002  C6, alternate sprint, C3 raises the skill and C5 the burst
#   90000003  C2, only two levelable talents, so it needs the calculator
#   90000004  C3 whose effect names none of its talents, so it needs the calculator

CALC_C = calculator_details([ATTACK, SKILL, BURST, *PASSIVES])  # 6/8/10
CALC_D = calculator_details([(20001, 5131, 2), (20002, 5132, 4), (20003, 5139, 4)])  # 2/4/4


def roster_api(*calculator: Any) -> FakeApi:
    """The fixture detail call, then one calculator result per fallback character."""
    return FakeApi(detail_characters(), *(calculator or (CALC_C, CALC_D)))


def test_fetch_roster_normalizes_characters() -> None:
    api = roster_api()
    result = run(make_client(api).fetch_roster())

    assert api.calls == [("detail", 800000000), ("calculator", 90000003), ("calculator", 90000004)]
    by_id = {c.hoyo_id: c for c in result.characters}
    assert len(by_id) == 4

    first = by_id[90000001]
    assert first.name == "Fixture Three Talents"
    assert first.element == "Pyro"
    assert first.weapon_type == "Sword"
    assert first.rarity == 5
    assert (first.level, first.ascension, first.ascension_ambiguous) == (90, 6, False)
    assert first.constellation == 0
    assert first.talents == Talents(normal=9, skill=9, burst=9)
    assert first.weapon.name == "Fixture Sword"
    assert (first.weapon.level, first.weapon.ascension, first.weapon.refinement) == (90, 6, 1)
    assert result.warnings == ()


def test_constellation_bonuses_are_taken_off_the_named_talents() -> None:
    result = run(make_client(roster_api()).fetch_roster())
    sprint = next(c for c in result.characters if c.hoyo_id == 90000002)

    # Detail shows 6/8/10 at C6. C3 named the skill and C5 the burst.
    assert sprint.weapon_type == "Catalyst"
    assert sprint.talents == Talents(normal=6, skill=5, burst=7)
    assert (sprint.level, sprint.ascension, sprint.ascension_ambiguous) == (80, 5, True)


def test_calculator_fills_in_when_detail_cant_settle_base_talents() -> None:
    result = run(make_client(roster_api()).fetch_roster())
    by_id = {c.hoyo_id: c for c in result.characters}

    assert by_id[90000003].talents == Talents(normal=6, skill=8, burst=10)
    assert by_id[90000004].talents == Talents(normal=2, skill=4, burst=4)
    assert result.notes == (
        "Fixture Odd Talents: talents from the calculator "
        "(expected 3 or 4 levelable talents, got 2)",
        "Fixture Unnamed Bonus: talents from the calculator "
        "(C3 effect names 0 talents, expected 1)",
    )
    assert result.warnings == ()


def test_failed_calculator_fallback_warns_and_leaves_talents_out() -> None:
    sync_off = genshin.errors.GenshinException({"retcode": -502002, "message": "sync off"})
    result = run(make_client(roster_api(sync_off, CALC_D)).fetch_roster())
    by_id = {c.hoyo_id: c for c in result.characters}

    assert by_id[90000003].talents is None
    assert by_id[90000004].talents == Talents(normal=2, skill=4, burst=4)
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.startswith("Fixture Odd Talents: expected 3 or 4 levelable talents, got 2")
    assert "calculator fallback failed" in warning
    assert "Calculator sync is off" in warning


def test_auth_error_in_calculator_fallback_stops_the_roster() -> None:
    expired = genshin.errors.InvalidCookies({"retcode": -100, "message": "Please login"})
    with pytest.raises(HoyolabAuthError):
        run(make_client(roster_api(expired)).fetch_roster())


# Base talents from character detail


def raw_character(index: int, **changes: Any) -> genshin.models.GenshinDetailCharacter:
    data = json.loads((FIXTURES / "character_detail.json").read_text(encoding="utf-8"))
    for key, value in changes.items():
        data["list"][index][key] = value
    return genshin.models.GenshinDetailCharacters(**data).characters[index]


def test_effect_naming_a_longer_talent_name_picks_the_longer_one() -> None:
    # Character A's skill "Fixture Ember" is part of the burst "Fixture Ember Storm".
    data = json.loads((FIXTURES / "character_detail.json").read_text(encoding="utf-8"))
    constellations = data["list"][0]["constellations"]
    for c in constellations:
        c["is_actived"] = c["pos"] <= 5
    raw = raw_character(0, constellations=constellations)
    raw = raw.model_copy(update={"constellation": 5})

    talents, reason = base_talents_from_detail(raw)
    # C3 names "Fixture Ember" (skill), C5 names "Fixture Ember Storm" (burst).
    assert reason is None
    assert talents == Talents(normal=9, skill=6, burst=6)


def test_constellation_data_that_disagrees_with_the_count_needs_the_calculator() -> None:
    raw = raw_character(1).model_copy(update={"constellation": 2})
    talents, reason = base_talents_from_detail(raw)
    assert talents is None
    assert reason == "C2 but 2 of C3/C5 shown as unlocked in the constellation data"


def test_bonus_that_would_leave_a_level_below_one_needs_the_calculator() -> None:
    data = json.loads((FIXTURES / "character_detail.json").read_text(encoding="utf-8"))
    skills = data["list"][1]["skills"]
    skills[1]["level"] = 2  # C3 would take the skill to -1
    talents, reason = base_talents_from_detail(raw_character(1, skills=skills))
    assert talents is None
    assert reason == "taking off constellation bonuses leaves a level below 1"


# Error mapping and retries (DESIGN.md section 11)


def test_invalid_cookies_become_auth_error_without_retry() -> None:
    api = FakeApi(genshin.errors.InvalidCookies({"retcode": -100, "message": "Please login"}))
    sleep = RecordingSleep()
    with pytest.raises(HoyolabAuthError, match="Refresh HOYOLAB_LTUID_V2"):
        run(make_client(api, sleep).fetch_roster())
    assert sleep.delays == []


@pytest.mark.parametrize("retcode", sorted(genshin.constants.GEETEST_RETCODES))
def test_captcha_retcodes_become_captcha_error(retcode: int) -> None:
    api = FakeApi(genshin.errors.GenshinException({"retcode": retcode, "message": "check"}))
    with pytest.raises(HoyolabCaptchaError, match="cloud IP"):
        run(make_client(api).fetch_roster())


def test_geetest_error_becomes_captcha_error() -> None:
    api = FakeApi(genshin.errors.GeetestError({"retcode": 0, "message": "geetest"}))
    with pytest.raises(HoyolabCaptchaError):
        run(make_client(api).fetch_roster())


def test_transient_errors_retry_with_backoff_then_succeed() -> None:
    api = FakeApi(
        genshin.errors.VisitsTooFrequently({"retcode": -110, "message": "slow down"}),
        aiohttp.ClientConnectionError("reset"),
        TimeoutError(),
        detail_characters(),
        CALC_C,
        CALC_D,
    )
    sleep = RecordingSleep()
    result = run(make_client(api, sleep).fetch_roster())

    assert len(result.characters) == 4
    assert sleep.delays == [1.0, 2.0, 4.0]


def test_transient_errors_give_up_after_three_retries() -> None:
    api = FakeApi(*[aiohttp.ClientConnectionError("down") for _ in range(4)])
    sleep = RecordingSleep()
    with pytest.raises(HoyolabUnavailableError, match="after 3 retries"):
        run(make_client(api, sleep).fetch_roster())
    assert sleep.delays == [1.0, 2.0, 4.0]
    assert len(api.calls) == 4


def test_other_api_errors_become_hoyolab_error() -> None:
    api = FakeApi(genshin.errors.DataNotPublic({"retcode": 10102, "message": "private"}))
    with pytest.raises(HoyolabError, match="Character list: .*10102"):
        run(make_client(api).fetch_roster())


def test_changed_response_shape_becomes_hoyolab_error() -> None:
    class ShapeChangedApi(FakeApi):
        async def get_genshin_detailed_characters(self, uid: int | None = None) -> Any:
            return genshin.models.GenshinDetailCharacters(**{"list": []})

    with pytest.raises(HoyolabError, match="API probably changed"):
        run(make_client(ShapeChangedApi()).fetch_roster())


# Calculator base talents


@pytest.mark.parametrize(
    "talents",
    [
        pytest.param([ATTACK, SKILL, BURST, *PASSIVES], id="three"),
        pytest.param([ATTACK, SKILL, SPRINT, BURST, *PASSIVES], id="four-with-sprint"),
    ],
)
def test_fetch_base_talents(talents: list[tuple[int, int, int]]) -> None:
    api = FakeApi(calculator_details(talents))
    result = run(make_client(api).fetch_base_talents(90000001))
    assert result == Talents(normal=6, skill=8, burst=10)
    assert api.calls == [("calculator", 90000001)]


def test_fetch_base_talents_rejects_unexpected_count() -> None:
    # genshin.py's upgradeable_talents would quietly return a passive as the burst here.
    api = FakeApi(calculator_details([ATTACK, SKILL, *PASSIVES]))
    with pytest.raises(HoyolabError, match="expected 3 or 4 non-passive talents, got 2"):
        run(make_client(api).fetch_base_talents(90000001))


def test_fetch_base_talents_explains_sync_off() -> None:
    api = FakeApi(genshin.errors.GenshinException({"retcode": -502002, "message": "sync off"}))
    with pytest.raises(HoyolabError, match="Calculator sync is off") as info:
        run(make_client(api).fetch_base_talents(90000001))
    assert info.value.retcode == -502002


def test_sync_off_is_detected_by_retcode_not_message() -> None:
    lookalike = genshin.errors.GenshinException({"retcode": -1, "message": "see [-502002]"})
    api = FakeApi(lookalike)
    with pytest.raises(HoyolabError) as info:
        run(make_client(api).fetch_base_talents(90000001))
    assert "Calculator sync is off" not in str(info.value)
    assert info.value.retcode == -1


def test_auth_error_keeps_retcode() -> None:
    api = FakeApi(genshin.errors.InvalidCookies({"retcode": 10001, "message": "Please login"}))
    with pytest.raises(HoyolabAuthError) as info:
        run(make_client(api).fetch_roster())
    assert info.value.retcode == 10001


# Construction from settings

FULL_ENV = {
    "HOYOLAB_LTUID_V2": "1",
    "HOYOLAB_LTOKEN_V2": "v2_fake",
    "HOYOLAB_LTMID_V2": "fake",
    "GENSHIN_UID": "800000000",
}


def test_from_settings_builds_a_genshin_client() -> None:
    client = HoyolabClient.from_settings(Settings.load(FULL_ENV))
    assert client.uid == 800000000
    assert isinstance(client._api, genshin.Client)
    assert repr(client) == "HoyolabClient()"


def test_from_settings_names_missing_keys_only() -> None:
    env = {**FULL_ENV, "HOYOLAB_LTOKEN_V2": "", "GENSHIN_UID": ""}
    with pytest.raises(ConfigError) as info:
        HoyolabClient.from_settings(Settings.load(env))
    message = str(info.value)
    assert "HOYOLAB_LTOKEN_V2" in message
    assert "GENSHIN_UID" in message
    assert "v2_fake" not in message


def test_from_settings_rejects_non_numeric_uid() -> None:
    with pytest.raises(ConfigError, match="GENSHIN_UID must be a number"):
        HoyolabClient.from_settings(Settings.load({**FULL_ENV, "GENSHIN_UID": "abc"}))
