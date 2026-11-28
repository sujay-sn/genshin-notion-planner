from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values

from gplanner.config import ConfigError, Settings, save_env_values


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
            "NOTION_DS_DAILY": "ds-id",
        }
    )
    assert s.local_tz == "Europe/Berlin"
    assert s.server_utc_offset == -5
    assert s.reset_hour == 3
    assert s.notion_token is None
    assert s.notion_ds_daily == "ds-id"


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


def test_notion_parent_page_and_data_sources_are_read() -> None:
    s = Settings.load({"NOTION_PARENT_PAGE_ID": "page-id", "NOTION_DS_CHARACTERS": "ds-chars"})
    assert s.notion_parent_page_id == "page-id"
    assert s.notion_ds_characters == "ds-chars"
    assert s.notion_ds_materials is None


def test_save_env_values_sets_keys_and_keeps_other_lines(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\nNOTION_TOKEN=keep-me\nNOTION_DS_NEEDS=\n", encoding="utf-8")

    save_env_values({"NOTION_DS_NEEDS": "ds-needs", "NOTION_DS_DAILY": "ds-daily"}, env)

    text = env.read_text(encoding="utf-8")
    assert "# comment" in text
    assert "NOTION_TOKEN=keep-me" in text
    assert "NOTION_DS_NEEDS=ds-needs" in text
    assert "NOTION_DS_DAILY=ds-daily" in text
    loaded = Settings.load(dotenv_values(env))
    assert (loaded.notion_ds_needs, loaded.notion_ds_daily) == ("ds-needs", "ds-daily")
