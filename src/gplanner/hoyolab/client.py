"""HoYoLAB access through genshin.py.

This module and ``map.py`` are the only places that import genshin.py or talk
to HoYoLAB (DESIGN.md section 3). Everything returned from here is one of the
project's own models, and every genshin.py error is turned into a
``HoyolabError`` subclass so callers never handle library exceptions.

Methods used, checked against genshin.py 1.7.32 (the pinned version):

* ``Client.get_genshin_detailed_characters(uid)``: ``character/list`` then
  ``character/detail`` for every owned ID. Two requests for the whole roster.
* ``Client.get_character_details(id)``: calculator ``sync/avatar/detail``, one
  request per character. Needs calculator sync turned on in HoYoLAB.

Calls that would change account settings are avoided on purpose:
``get_genshin_notes`` must get ``autoauth=False`` (M4), and
``get_calculator_characters(sync=True)`` is not used because it turns on
calculator sync silently.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol, TypeVar

import aiohttp
import genshin
import pydantic

from gplanner.config import ConfigError, Settings
from gplanner.models import (
    CharacterSnapshot,
    RosterResult,
    Talents,
    WeaponSnapshot,
    ascension_for_level,
)

T = TypeVar("T")

# HoYoLAB's skill_type for talents you can level. 2 is passives.
_ACTIVE_SKILL_TYPE = 1
# Calculator retcode when sync is off (genshin.errors maps it to a plain message).
_CALCULATOR_SYNC_OFF = -502002


class HoyolabError(Exception):
    """A HoYoLAB step failed. The message is safe to print: it never holds secrets.

    ``retcode`` is HoYoLAB's error code when the API returned one, so callers
    can branch on it instead of parsing the message.
    """

    def __init__(self, message: str, *, retcode: int | None = None) -> None:
        super().__init__(message)
        self.retcode = retcode


class HoyolabAuthError(HoyolabError):
    """The cookies were rejected. They need refreshing."""


class HoyolabCaptchaError(HoyolabError):
    """HoYoLAB asked for a captcha. Most likely the run came from a cloud IP."""


class HoyolabUnavailableError(HoyolabError):
    """Transient errors or rate limits outlasted the retries."""


class GenshinApi(Protocol):
    """The slice of ``genshin.Client`` this module uses. Tests pass a fake."""

    async def get_genshin_detailed_characters(
        self, uid: int | None = None
    ) -> genshin.models.GenshinDetailCharacters: ...

    async def get_character_details(
        self, character: int, *, uid: int | None = None
    ) -> genshin.models.CalculatorCharacterDetails: ...


_RETRYABLE: tuple[type[BaseException], ...] = (
    genshin.errors.VisitsTooFrequently,
    aiohttp.ClientError,
    TimeoutError,
)


def _is_captcha(exc: genshin.errors.GenshinException) -> bool:
    return (
        isinstance(exc, genshin.errors.GeetestError | genshin.errors.DailyGeetestTriggered)
        or exc.retcode in genshin.constants.GEETEST_RETCODES
    )


class HoyolabClient:
    """Async adapter over genshin.py for one account."""

    def __init__(
        self,
        api: GenshinApi,
        uid: int,
        *,
        retries: int = 3,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self._api = api
        self.uid = uid
        self._retries = retries
        self._backoff = backoff_seconds
        self._sleep = sleep

    def __repr__(self) -> str:
        # Never show the UID or anything from the underlying client.
        return f"{type(self).__name__}()"

    @classmethod
    def from_settings(cls, settings: Settings) -> HoyolabClient:
        required = {
            "HOYOLAB_LTUID_V2": settings.hoyolab_ltuid_v2,
            "HOYOLAB_LTOKEN_V2": settings.hoyolab_ltoken_v2,
            "HOYOLAB_LTMID_V2": settings.hoyolab_ltmid_v2,
            "GENSHIN_UID": settings.genshin_uid,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ConfigError(f"Missing in .env: {', '.join(missing)}")
        try:
            uid = int(settings.genshin_uid or "")
        except ValueError:
            raise ConfigError("GENSHIN_UID must be a number") from None

        cookies = {
            "ltuid_v2": settings.hoyolab_ltuid_v2,
            "ltoken_v2": settings.hoyolab_ltoken_v2,
            "ltmid_v2": settings.hoyolab_ltmid_v2,
        }
        api = genshin.Client(cookies, game=genshin.Game.GENSHIN, uid=uid, lang="en-us")
        return cls(api, uid)

    async def _call(self, step: str, fn: Callable[[], Awaitable[T]]) -> T:
        """Run one HoYoLAB request with retries, mapping errors (DESIGN.md section 11)."""
        attempt = 0
        while True:
            try:
                return await fn()
            except genshin.errors.InvalidCookies as exc:
                raise HoyolabAuthError(
                    f"{step}: HoYoLAB rejected the cookies ({exc}). "
                    "Refresh HOYOLAB_LTUID_V2, HOYOLAB_LTOKEN_V2 and HOYOLAB_LTMID_V2 in .env.",
                    retcode=exc.retcode or None,
                ) from None
            except _RETRYABLE as exc:
                if attempt >= self._retries:
                    raise HoyolabUnavailableError(
                        f"{step}: still failing after {self._retries} retries ({exc!s})"
                    ) from None
                await self._sleep(self._backoff * 2**attempt)
                attempt += 1
            except genshin.errors.GenshinException as exc:
                if _is_captcha(exc):
                    raise HoyolabCaptchaError(
                        f"{step}: HoYoLAB asked for a captcha ({exc}). "
                        "This usually means the request came from a cloud IP. Run it locally.",
                        retcode=exc.retcode or None,
                    ) from None
                raise HoyolabError(f"{step}: {exc}", retcode=exc.retcode or None) from None
            except pydantic.ValidationError as exc:
                raise HoyolabError(
                    f"{step}: the response no longer matches genshin.py's model, "
                    f"so the API probably changed ({exc.error_count()} errors)"
                ) from None

    async def fetch_roster(self) -> RosterResult:
        """Every owned character with level, constellation, talents and weapon."""
        data = await self._call(
            "Character list", lambda: self._api.get_genshin_detailed_characters(self.uid)
        )
        characters: list[CharacterSnapshot] = []
        warnings: list[str] = []
        for raw in data.characters:
            snapshot, problems = normalize_character(raw)
            characters.append(snapshot)
            warnings.extend(problems)
        return RosterResult(tuple(characters), tuple(warnings))

    async def fetch_base_talents(self, character_id: int) -> Talents:
        """Talent levels from the calculator, which works on base levels.

        Used by the live test to check whether the character detail levels
        include constellation bonuses. The calculator (M3) will use it too.
        """

        async def request() -> genshin.models.CalculatorCharacterDetails:
            return await self._api.get_character_details(character_id, uid=self.uid)

        try:
            details = await self._call("Calculator character details", request)
        except HoyolabError as exc:
            if exc.retcode == _CALCULATOR_SYNC_OFF:
                raise HoyolabError(
                    "Calculator sync is off. Turn it on in HoYoLAB's Enhancement "
                    "Progression Calculator, then run again.",
                    retcode=exc.retcode,
                ) from None
            raise
        # Not genshin.py's upgradeable_talents: it always returns three and only
        # looks for the sprint at index 2.
        active = [t.level for t in details.talents if t.type != "passive"]
        talents = _talents_from_levels(active)
        if talents is None:
            raise HoyolabError(
                f"Calculator character details: expected 3 or 4 non-passive talents, "
                f"got {len(active)}"
            )
        return talents


def _talents_from_levels(levels: Sequence[int]) -> Talents | None:
    """Normal attack, skill and burst from the levels of a character's active talents.

    Most characters have three. A few (alternate sprint, like Kamisato Ayaka or
    Mona) have a fourth that sits before the burst, so the burst is always the
    last one. The live test prints the four-talent characters so this ordering
    can be confirmed. Any other count returns None.
    """
    if len(levels) not in (3, 4):
        return None
    return Talents(normal=levels[0], skill=levels[1], burst=levels[-1])


def _pick_talents(skills: Sequence[Any]) -> Talents | None:
    """Talents from the character detail skills, where levelable ones have skill_type 1."""
    return _talents_from_levels([s.level for s in skills if s.skill_type == _ACTIVE_SKILL_TYPE])


def normalize_character(
    raw: genshin.models.GenshinDetailCharacter,
) -> tuple[CharacterSnapshot, list[str]]:
    """Turn one genshin.py detailed character into a ``CharacterSnapshot``."""
    problems: list[str] = []

    talents = _pick_talents(raw.skills)
    if talents is None:
        count = sum(1 for s in raw.skills if s.skill_type == _ACTIVE_SKILL_TYPE)
        problems.append(f"{raw.name}: expected 3 or 4 levelable talents, got {count}")

    ascension, ambiguous = ascension_for_level(raw.level)
    weapon = raw.weapon
    snapshot = CharacterSnapshot(
        hoyo_id=raw.id,
        name=raw.name,
        element=raw.element,
        weapon_type=raw.weapon_type.name.title(),
        rarity=raw.rarity,
        level=raw.level,
        ascension=ascension,
        ascension_ambiguous=ambiguous,
        constellation=raw.constellation,
        talents=talents,
        weapon=WeaponSnapshot(
            hoyo_id=weapon.id,
            name=weapon.name,
            rarity=weapon.rarity,
            level=weapon.level,
            ascension=weapon.ascension,
            refinement=weapon.refinement,
        ),
    )
    return snapshot, problems
