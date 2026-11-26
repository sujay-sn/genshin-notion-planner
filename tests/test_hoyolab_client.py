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


def test_fetch_roster_normalizes_characters() -> None:
    api = FakeApi(detail_characters())
    result = run(make_client(api).fetch_roster())

    assert api.calls == [("detail", 800000000)]
    by_id = {c.hoyo_id: c for c in result.characters}
    assert len(by_id) == 3

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


def test_sprint_talent_is_skipped_and_burst_is_last() -> None:
    result = run(make_client(FakeApi(detail_characters())).fetch_roster())
    sprint = next(c for c in result.characters if c.hoyo_id == 90000002)

    assert sprint.weapon_type == "Catalyst"
    assert sprint.talents == Talents(normal=6, skill=8, burst=10)
    assert (sprint.level, sprint.ascension, sprint.ascension_ambiguous) == (80, 5, True)


def test_unexpected_talent_count_gives_none_and_a_warning() -> None:
    result = run(make_client(FakeApi(detail_characters())).fetch_roster())
    odd = next(c for c in result.characters if c.hoyo_id == 90000003)

    assert odd.talents is None
    assert odd.weapon_type == "Bow"
    assert result.warnings == ("Fixture Odd Talents: expected 3 or 4 levelable talents, got 2",)


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
    )
    sleep = RecordingSleep()
    result = run(make_client(api, sleep).fetch_roster())

    assert len(result.characters) == 3
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
