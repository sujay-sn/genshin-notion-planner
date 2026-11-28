from __future__ import annotations

from typing import Any

import pytest

from fake_notion import FakeNotion
from gplanner import cli
from gplanner.config import Settings
from gplanner.hoyolab.client import HoyolabAuthError
from gplanner.models import CharacterSnapshot, RosterResult, Talents, WeaponSnapshot
from gplanner.notion.repo import plan_roster


def snapshot(**overrides: object) -> CharacterSnapshot:
    fields: dict[str, object] = {
        "hoyo_id": 90000001,
        "name": "Fixture A",
        "element": "Pyro",
        "weapon_type": "Sword",
        "rarity": 5,
        "level": 90,
        "ascension": 6,
        "ascension_ambiguous": False,
        "constellation": 1,
        "talents": Talents(9, 8, 10),
        "weapon": WeaponSnapshot(91000001, "Fixture Sword", 5, 90, 6, 1),
    }
    fields.update(overrides)
    return CharacterSnapshot(**fields)  # type: ignore[arg-type]


def test_format_roster_orders_and_marks_ambiguous_ascension() -> None:
    result = RosterResult(
        (
            snapshot(
                hoyo_id=2,
                name="Four Star",
                rarity=4,
                level=80,
                ascension=5,
                ascension_ambiguous=True,
                talents=None,
            ),
            snapshot(),
        )
    )
    lines = cli.format_roster(result).splitlines()

    assert lines[0].split() == [
        "Name",
        "Element",
        "Weapon",
        "type",
        "Rarity",
        "Lv",
        "Asc",
        "C",
        "N/S/B",
        "Weapon",
    ]
    assert lines[2].startswith("Fixture A")
    assert "9/8/10" in lines[2]
    assert "Fixture Sword Lv90 R1" in lines[2]
    assert lines[3].startswith("Four Star")
    assert " 5? " in lines[3]
    assert " - " in lines[3]
    assert "2 characters." in lines
    assert any(line.startswith("Asc with ?") for line in lines)


# sync-roster


class FakeHoyolab:
    def __init__(self, roster: RosterResult) -> None:
        self.roster = roster

    async def fetch_roster(self) -> RosterResult:
        return self.roster


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """CLI wired to a fake Notion, a fake HoYoLAB and an in-memory .env."""
    fake = FakeNotion()
    env: dict[str, str] = {"NOTION_TOKEN": "fake", "NOTION_PARENT_PAGE_ID": "parent-page"}
    state: dict[str, Any] = {"fake": fake, "env": env, "roster": RosterResult((snapshot(),))}

    real_load = Settings.load
    monkeypatch.setattr(cli.Settings, "load", classmethod(lambda cls: real_load(dict(env))))
    monkeypatch.setattr(cli, "make_client", lambda settings: fake)
    monkeypatch.setattr(cli, "save_env_values", lambda values: env.update(values))
    monkeypatch.setattr(
        cli.HoyolabClient, "from_settings", classmethod(lambda cls, s: FakeHoyolab(state["roster"]))
    )
    return state


def test_format_plan_lists_creates_and_changes() -> None:
    first = plan_roster([snapshot()], [], "2026-11-28T20:05:00+00:00")
    text = cli.format_plan(first, dry_run=True)
    assert text.splitlines() == [
        "+ Fixture A",
        "Characters: 1 to create, 0 to update, 0 unchanged.",
    ]


def test_init_then_sync_then_sync_again_writes_nothing_the_second_time(
    workspace: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    fake: FakeNotion = workspace["fake"]
    assert cli.main(["init-notion"]) == cli.EXIT_OK
    assert "All four databases match the expected schema." in capsys.readouterr().out
    assert "NOTION_DS_CHARACTERS" in workspace["env"]

    assert cli.main(["sync-roster"]) == cli.EXIT_OK
    assert "Characters: 1 created, 0 updated, 0 unchanged." in capsys.readouterr().out
    writes = len(fake.writes())

    assert cli.main(["sync-roster"]) == cli.EXIT_OK
    assert "Characters: 0 created, 0 updated, 1 unchanged." in capsys.readouterr().out
    assert len(fake.writes()) == writes
    assert fake.closed


def test_sync_roster_dry_run_writes_nothing(
    workspace: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["init-notion"])
    fake: FakeNotion = workspace["fake"]
    writes = len(fake.writes())
    workspace["roster"] = RosterResult(
        (snapshot(),), warnings=("Fixture B: something odd",), notes=("Fixture A: a note",)
    )
    capsys.readouterr()

    assert cli.main(["sync-roster", "--dry-run"]) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert "+ Fixture A" in out
    assert "Dry run: nothing was written." in out
    assert "note: Fixture A: a note" in out
    assert "warning: Fixture B: something odd" in err
    assert len(fake.writes()) == writes


def test_sync_roster_reports_auth_failure(
    workspace: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["init-notion"])

    class Expired:
        async def fetch_roster(self) -> RosterResult:
            raise HoyolabAuthError("Character list: cookies rejected")

    monkeypatch.setattr(cli.HoyolabClient, "from_settings", classmethod(lambda cls, s: Expired()))
    capsys.readouterr()

    assert cli.main(["sync-roster"]) == cli.EXIT_FAILED
    assert "error: Character list: cookies rejected" in capsys.readouterr().err


def test_sync_roster_before_init_says_to_run_it(
    workspace: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["sync-roster"]) == cli.EXIT_FAILED
    assert "NOTION_DS_CHARACTERS is not set. Run init-notion." in capsys.readouterr().err


def test_missing_notion_token_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.Settings, "load", classmethod(lambda cls: Settings()))
    assert cli.main(["sync-roster", "--dry-run"]) == cli.EXIT_FAILED
    assert "Missing in .env: NOTION_TOKEN" in capsys.readouterr().err


# init-notion


def test_init_notion_check_reports_problems(
    workspace: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["init-notion"])
    fake: FakeNotion = workspace["fake"]
    props = fake.sources[workspace["env"]["NOTION_DS_CHARACTERS"]]["properties"]
    props["Lvl"] = props.pop("Level")
    capsys.readouterr()

    assert cli.main(["init-notion", "--check"]) == cli.EXIT_FAILED
    err = capsys.readouterr().err
    assert "problem: Characters: property 'Level' is missing (renamed or deleted?)" in err


def test_init_notion_dry_run_writes_nothing(
    workspace: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["init-notion", "--dry-run"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Would create Characters with 20 properties" in out
    assert "Dry run: nothing was written." in out
    assert workspace["fake"].calls == []
    assert "NOTION_DS_CHARACTERS" not in workspace["env"]
