from __future__ import annotations

import pytest

from gplanner.config import ConfigError, Settings


def test_defaults_match_env_example() -> None:
    s = Settings.load({})
    assert s.local_tz == "America/New_York"
    assert s.server_utc_offset == 8
    assert s.reset_hour == 4
    assert s.specialty_respawn_hours == 48
    assert s.notion_token is None


def test_values_are_read_and_blank_means_unset() -> None:
    s = Settings.load(
        {
            "LOCAL_TZ": "Europe/Berlin",
            "SERVER_UTC_OFFSET": "-5",
            "RESET_HOUR": " 3 ",
            "NOTION_TOKEN": "",
            "NOTION_DB_DAILY": "db-id",
        }
    )
    assert s.local_tz == "Europe/Berlin"
    assert s.server_utc_offset == -5
    assert s.reset_hour == 3
    assert s.notion_token is None
    assert s.notion_db_daily == "db-id"


@pytest.mark.parametrize(
    "env",
    [
        {"LOCAL_TZ": "Not/AZone"},
        {"SERVER_UTC_OFFSET": "15"},
        {"SERVER_UTC_OFFSET": "eight"},
        {"RESET_HOUR": "24"},
        {"RESET_HOUR": "-1"},
        {"SPECIALTY_RESPAWN_HOURS": "0"},
    ],
)
def test_invalid_values_raise(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        Settings.load(env)


def test_secrets_not_in_repr() -> None:
    s = Settings.load(
        {
            "HOYOLAB_LTUID_V2": "fake-ltuid",
            "HOYOLAB_LTOKEN_V2": "fake-ltoken",
            "HOYOLAB_LTMID_V2": "fake-ltmid",
            "GENSHIN_UID": "fake-uid",
            "NOTION_TOKEN": "fake-notion-token",
        }
    )
    text = repr(s)
    for secret in ("fake-ltuid", "fake-ltoken", "fake-ltmid", "fake-uid", "fake-notion-token"):
        assert secret not in text
