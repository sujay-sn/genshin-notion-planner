"""Settings loaded from the environment and .env.

This is the only module that reads secrets. Everything else gets a
``Settings`` object. Secret fields are excluded from ``repr`` so they can't
leak into logs or tracebacks.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import dotenv_values, set_key


class ConfigError(ValueError):
    """A config value is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    # Time model (DESIGN.md section 7)
    local_tz: str = "America/New_York"
    server_utc_offset: int = 8
    reset_hour: int = 4
    specialty_respawn_hours: int = 48

    # Secrets. Optional until the milestone that needs them.
    hoyolab_ltuid_v2: str | None = field(default=None, repr=False)
    hoyolab_ltoken_v2: str | None = field(default=None, repr=False)
    hoyolab_ltmid_v2: str | None = field(default=None, repr=False)
    genshin_uid: str | None = field(default=None, repr=False)
    notion_token: str | None = field(default=None, repr=False)

    # Notion page the databases live under, and the data source IDs that
    # init-notion writes. Under Notion API 2025-09-03 pages, queries and
    # relations all address a database's data source, not the database.
    notion_parent_page_id: str | None = None
    notion_ds_characters: str | None = None
    notion_ds_materials: str | None = None
    notion_ds_needs: str | None = None
    notion_ds_daily: str | None = None

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.local_tz)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(f"LOCAL_TZ is not a known time zone: {self.local_tz!r}") from exc
        if not -12 <= self.server_utc_offset <= 14:
            raise ConfigError(
                f"SERVER_UTC_OFFSET must be between -12 and 14, got {self.server_utc_offset}"
            )
        if not 0 <= self.reset_hour <= 23:
            raise ConfigError(f"RESET_HOUR must be between 0 and 23, got {self.reset_hour}")
        if self.specialty_respawn_hours <= 0:
            raise ConfigError(
                f"SPECIALTY_RESPAWN_HOURS must be positive, got {self.specialty_respawn_hours}"
            )

    @classmethod
    def load(cls, env: Mapping[str, str | None] | None = None) -> Settings:
        """Build settings from ``env``, or from ``.env`` plus the process environment.

        Process environment variables win over ``.env``. Pass ``env`` explicitly
        in tests so no real ``.env`` is read.
        """
        if env is None:
            env = {**dotenv_values(Path.cwd() / ".env"), **os.environ}

        def text(key: str) -> str | None:
            value = env.get(key)
            if value is None:
                return None
            value = value.strip()
            return value or None

        def integer(key: str, default: int) -> int:
            value = text(key)
            if value is None:
                return default
            try:
                return int(value)
            except ValueError as exc:
                raise ConfigError(f"{key} must be an integer, got {value!r}") from exc

        defaults = cls.__dataclass_fields__
        return cls(
            local_tz=text("LOCAL_TZ") or defaults["local_tz"].default,
            server_utc_offset=integer("SERVER_UTC_OFFSET", defaults["server_utc_offset"].default),
            reset_hour=integer("RESET_HOUR", defaults["reset_hour"].default),
            specialty_respawn_hours=integer(
                "SPECIALTY_RESPAWN_HOURS", defaults["specialty_respawn_hours"].default
            ),
            hoyolab_ltuid_v2=text("HOYOLAB_LTUID_V2"),
            hoyolab_ltoken_v2=text("HOYOLAB_LTOKEN_V2"),
            hoyolab_ltmid_v2=text("HOYOLAB_LTMID_V2"),
            genshin_uid=text("GENSHIN_UID"),
            notion_token=text("NOTION_TOKEN"),
            notion_parent_page_id=text("NOTION_PARENT_PAGE_ID"),
            notion_ds_characters=text("NOTION_DS_CHARACTERS"),
            notion_ds_materials=text("NOTION_DS_MATERIALS"),
            notion_ds_needs=text("NOTION_DS_NEEDS"),
            notion_ds_daily=text("NOTION_DS_DAILY"),
        )


def save_env_values(values: Mapping[str, str], path: Path | None = None) -> None:
    """Set keys in ``.env``, keeping every other line as it is.

    init-notion uses this to record data source IDs. Values are written
    unquoted, matching ``.env.example``.
    """
    env_path = path or Path.cwd() / ".env"
    env_path.touch(exist_ok=True)
    for key, value in values.items():
        set_key(env_path, key, value, quote_mode="never")
