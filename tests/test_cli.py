from __future__ import annotations

import pytest

from gplanner import cli
from gplanner.config import Settings
from gplanner.hoyolab.client import HoyolabAuthError
from gplanner.models import CharacterSnapshot, RosterResult, Talents, WeaponSnapshot


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


def test_sync_roster_without_dry_run_refuses(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["sync-roster"]) == cli.EXIT_USAGE
    assert "--dry-run" in capsys.readouterr().err


def test_sync_roster_dry_run_prints_roster(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_sync(settings: Settings) -> RosterResult:
        return RosterResult((snapshot(),), ("Fixture A: something odd",))

    monkeypatch.setattr(cli.Settings, "load", classmethod(lambda cls: Settings()))
    monkeypatch.setattr(cli, "_sync_roster", fake_sync)

    assert cli.main(["sync-roster", "--dry-run"]) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert "Fixture A" in out
    assert "Dry run: nothing was written." in out
    assert "warning: Fixture A: something odd" in err


def test_sync_roster_dry_run_reports_auth_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def failing_sync(settings: Settings) -> RosterResult:
        raise HoyolabAuthError("Character list: cookies rejected")

    monkeypatch.setattr(cli.Settings, "load", classmethod(lambda cls: Settings()))
    monkeypatch.setattr(cli, "_sync_roster", failing_sync)

    assert cli.main(["sync-roster", "--dry-run"]) == cli.EXIT_FAILED
    assert "error: Character list: cookies rejected" in capsys.readouterr().err


def test_sync_roster_dry_run_reports_missing_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.Settings, "load", classmethod(lambda cls: Settings()))

    assert cli.main(["sync-roster", "--dry-run"]) == cli.EXIT_FAILED
    assert "Missing in .env: HOYOLAB_LTUID_V2" in capsys.readouterr().err
