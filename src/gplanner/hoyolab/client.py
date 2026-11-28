"""HoYoLAB access through genshin.py.

This module and ``map.py`` are the only places that import genshin.py or talk
to HoYoLAB (DESIGN.md section 3). Everything returned from here is one of the
project's own models, and every genshin.py error is turned into a
``HoyolabError`` subclass so callers never handle library exceptions.

Methods used, checked against genshin.py 1.7.32 (the pinned version):

* ``Client.get_genshin_detailed_characters(uid)``: ``character/list`` then
  ``character/detail`` for every owned ID. Two requests for the whole roster.
* ``Client.get_character_details(id)``: calculator ``sync/avatar/detail``, one
  request per character. Needs calculator sync turned on in HoYoLAB. Used only
  for characters whose base talents can't be worked out from character detail.

Calls that would change account settings are avoided on purpose:
``get_genshin_notes`` must get ``autoauth=False`` (M4), and
``get_calculator_characters(sync=True)`` is not used because it turns on
calculator sync silently.
"""

from __future__ import annotations

import asyncio
import dataclasses
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
# Constellations that raise one talent by 3 levels (DESIGN.md section 4.1).
_BONUS_CONSTELLATIONS = (3, 5)
_TALENT_BONUS = 3
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
        """Every owned character with level, constellation, base talents and weapon.

        Base talents come from character detail with constellation bonuses taken
        off. When that can't be done reliably for a character, their talents
        come from the calculator instead (one request each).
        """
        data = await self._call(
            "Character list", lambda: self._api.get_genshin_detailed_characters(self.uid)
        )
        characters: list[CharacterSnapshot] = []
        warnings: list[str] = []
        notes: list[str] = []
        for raw in data.characters:
            snapshot, reason = normalize_character(raw)
            if reason is not None:
                try:
                    talents = await self.fetch_base_talents(snapshot.hoyo_id)
                except HoyolabAuthError:
                    raise
                except HoyolabError as exc:
                    warnings.append(
                        f"{snapshot.name}: {reason}, and the calculator fallback failed "
                        f"({exc}). Talents left out of this sync."
                    )
                else:
                    snapshot = dataclasses.replace(snapshot, talents=talents)
                    notes.append(f"{snapshot.name}: talents from the calculator ({reason})")
            characters.append(snapshot)
        return RosterResult(tuple(characters), tuple(warnings), tuple(notes))

    async def fetch_base_talents(self, character_id: int) -> Talents:
        """Talent levels from the calculator, which works on base levels.

        The fallback for ``fetch_roster`` when character detail can't settle
        base levels. The live test also uses it to check the bonus removal.
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


def _most_specific(matched: dict[str, str]) -> list[str]:
    """Keys of matched talent names, minus any name that's part of a longer match.

    An effect naming "Foo Bar" also contains "Foo", so a talent called "Foo"
    would otherwise count as named too.
    """
    folded = {key: name.casefold() for key, name in matched.items()}
    return [
        key
        for key, name in folded.items()
        if not any(other != key and name in longer for other, longer in folded.items())
    ]


def base_talents_from_detail(
    raw: genshin.models.GenshinDetailCharacter,
) -> tuple[Talents | None, str | None]:
    """Base talent levels from character detail, or None and the reason it can't tell.

    Character detail levels include constellation bonuses. Each unlocked C3
    and C5 raises one talent by 3, and its effect text names that talent, so
    the bonus is taken off the talent it names. If an effect names no talent
    or several, or the constellation data doesn't match the constellation
    count, the caller falls back to the calculator.
    """
    active = [s for s in raw.skills if s.skill_type == _ACTIVE_SKILL_TYPE]
    if len(active) not in (3, 4):
        return None, f"expected 3 or 4 levelable talents, got {len(active)}"

    # With four, the third is the alternate sprint, which no constellation raises.
    talents = {"normal": active[0], "skill": active[1], "burst": active[-1]}
    levels = {key: skill.level for key, skill in talents.items()}

    expected = sum(1 for pos in _BONUS_CONSTELLATIONS if raw.constellation >= pos)
    unlocked = [c for c in raw.constellations if c.pos in _BONUS_CONSTELLATIONS and c.activated]
    if len(unlocked) != expected:
        return None, (
            f"C{raw.constellation} but {len(unlocked)} of C3/C5 shown as unlocked "
            "in the constellation data"
        )

    for constellation in unlocked:
        effect = constellation.effect.casefold()
        keys = _most_specific(
            {key: skill.name for key, skill in talents.items() if skill.name.casefold() in effect}
        )
        if len(keys) != 1:
            return None, f"C{constellation.pos} effect names {len(keys)} talents, expected 1"
        levels[keys[0]] -= _TALENT_BONUS

    if any(level < 1 for level in levels.values()):
        return None, "taking off constellation bonuses leaves a level below 1"
    return Talents(normal=levels["normal"], skill=levels["skill"], burst=levels["burst"]), None


def normalize_character(
    raw: genshin.models.GenshinDetailCharacter,
) -> tuple[CharacterSnapshot, str | None]:
    """Turn one genshin.py detailed character into a ``CharacterSnapshot``.

    Returns the snapshot and, when base talents couldn't be worked out, the
    reason. The snapshot's talents are None in that case.
    """
    talents, reason = base_talents_from_detail(raw)
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
    return snapshot, reason
