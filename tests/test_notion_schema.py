"""init-notion and --check against the in-memory fake Notion. No network."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from fake_notion import FakeNotion
from gplanner.config import ConfigError, Settings
from gplanner.notion.client import NotionSchemaError
from gplanner.notion.schema import (
    CHARACTERS,
    DATABASES,
    MATERIALS,
    NEEDS,
    check_workspace,
    init_workspace,
    require_schema,
)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class SavedIds:
    def __init__(self) -> None:
        self.saved: dict[str, str] = {}
        self.calls = 0

    def __call__(self, values: Mapping[str, str]) -> None:
        self.calls += 1
        self.saved.update(values)


def settings(**ids: str) -> Settings:
    return Settings(notion_parent_page_id="parent-page", **ids)


def settings_from(saved: Mapping[str, str]) -> Settings:
    return settings(
        **{spec.settings_attr: saved[spec.env_key] for spec in DATABASES if spec.env_key in saved}
    )


def init(fake: FakeNotion, s: Settings, save: SavedIds | None = None, **kw: Any) -> list[str]:
    return run(init_workspace(fake, s, save or SavedIds(), **kw))


def test_init_creates_all_four_databases_and_saves_each_id() -> None:
    fake, save = FakeNotion(), SavedIds()
    log = init(fake, settings(), save)

    created = [c[1] for c in fake.calls if c[0] == "databases.create"]
    assert [c["title"][0]["text"]["content"] for c in created] == [
        "Characters",
        "Materials",
        "Needs",
        "Daily Log",
    ]
    assert all(c["parent"] == {"type": "page_id", "page_id": "parent-page"} for c in created)
    # Saved one at a time, as each database is created.
    assert save.calls == 4
    assert set(save.saved) == {spec.env_key for spec in DATABASES}
    assert any("Renamed Materials relation" in line for line in log)
    assert run(check_workspace(fake, settings_from(save.saved))) == []


def test_needs_relations_point_at_the_right_data_sources() -> None:
    fake, save = FakeNotion(), SavedIds()
    init(fake, settings(), save)

    needs = fake.sources[save.saved[NEEDS.env_key]]["properties"]
    assert needs["Character"]["relation"]["data_source_id"] == save.saved[CHARACTERS.env_key]
    assert needs["Character"]["relation"]["type"] == "single_property"
    assert needs["Material"]["relation"]["data_source_id"] == save.saved[MATERIALS.env_key]
    assert needs["Material"]["relation"]["type"] == "dual_property"


def test_materials_gets_rollup_and_formulas_with_48_hour_respawn() -> None:
    fake, save = FakeNotion(), SavedIds()
    init(fake, settings(), save)

    materials = fake.sources[save.saved[MATERIALS.env_key]]["properties"]
    assert materials["Needs"]["type"] == "relation"
    assert materials["Needed"]["rollup"] == {
        "relation_property_name": "Needs",
        "rollup_property_name": "Quantity",
        "function": "sum",
    }
    assert materials["Back at"]["formula"]["expression"] == (
        'dateAdd(prop("Last collected"), 48, "hours")'
    )
    assert 'prop("Needed")' in materials["Short by"]["formula"]["expression"]
    assert 'empty(prop("Owned"))' in materials["Short by"]["formula"]["expression"]


def test_reverse_relation_already_named_needs_is_left_alone() -> None:
    fake = FakeNotion(honor_synced_name=True)
    log = init(fake, settings())
    assert not any("Renamed" in line for line in log)
    updates = [c[1]["properties"] for c in fake.calls if c[0] == "data_sources.update"]
    renames = [cfg for props in updates for cfg in props.values() if set(cfg) == {"name"}]
    assert renames == []


def test_partial_create_response_reads_the_database_for_its_data_source() -> None:
    fake, save = FakeNotion(partial_create=True), SavedIds()
    init(fake, settings(), save)
    assert len([c for c in fake.calls if c[0] == "databases.retrieve"]) == 4
    assert all(value.startswith("ds-") for value in save.saved.values())


def test_running_init_again_writes_nothing() -> None:
    fake, save = FakeNotion(), SavedIds()
    init(fake, settings(), save)
    writes_before = len(fake.writes())

    log = init(fake, settings_from(save.saved))

    assert len(fake.writes()) == writes_before
    assert sum("already set up" in line for line in log) == 4
    assert "Materials: relation, rollup and formulas already in place" in log


def test_init_resumes_after_stopping_partway() -> None:
    fake, save = FakeNotion(), SavedIds()
    # Pretend only Characters got created before a crash.
    chars_id = fake.add_source("Characters", CHARACTERS.expected_types())

    init(fake, settings(notion_ds_characters=chars_id), save)

    created = [
        c[1]["title"][0]["text"]["content"] for c in fake.calls if c[0] == "databases.create"
    ]
    assert created == ["Materials", "Needs", "Daily Log"]
    needs = fake.sources[save.saved[NEEDS.env_key]]["properties"]
    assert needs["Character"]["relation"]["data_source_id"] == chars_id


def test_dry_run_on_a_fresh_page_makes_no_calls() -> None:
    fake = FakeNotion()
    log = init(fake, settings(), dry_run=True)
    assert fake.calls == []
    assert log[:4] == [
        "Would create Characters with 20 properties",
        "Would create Materials with 11 properties",
        "Would create Needs with 4 properties",
        "Would create Daily Log with 9 properties",
    ]
    assert log[4].startswith("Would add to Materials")


def test_dry_run_on_a_set_up_workspace_only_reads() -> None:
    fake, save = FakeNotion(), SavedIds()
    init(fake, settings(), save)
    writes_before = len(fake.writes())
    init(fake, settings_from(save.saved), dry_run=True)
    assert len(fake.writes()) == writes_before


def test_init_needs_a_parent_page() -> None:
    with pytest.raises(ConfigError, match="NOTION_PARENT_PAGE_ID"):
        init(FakeNotion(), Settings())


# --check


def set_up() -> tuple[FakeNotion, dict[str, str]]:
    fake, save = FakeNotion(), SavedIds()
    init(fake, settings(), save)
    return fake, save.saved


def test_check_names_a_renamed_property() -> None:
    fake, ids = set_up()
    props = fake.sources[ids[CHARACTERS.env_key]]["properties"]
    props["Lvl"] = props.pop("Level")

    problems = run(check_workspace(fake, settings_from(ids)))
    assert problems == ["Characters: property 'Level' is missing (renamed or deleted?)"]


def test_check_names_a_property_with_the_wrong_type() -> None:
    fake, ids = set_up()
    fake.sources[ids[CHARACTERS.env_key]]["properties"]["Priority"] = {
        "type": "rich_text",
        "rich_text": {},
    }
    problems = run(check_workspace(fake, settings_from(ids)))
    assert problems == ["Characters: property 'Priority' is rich_text, expected number"]


def test_check_reports_unset_ids_and_missing_databases() -> None:
    fake, ids = set_up()
    del fake.sources[ids[NEEDS.env_key]]
    s = settings_from({k: v for k, v in ids.items() if k != "NOTION_DS_DAILY"})

    problems = run(check_workspace(fake, s))
    assert len(problems) == 2
    assert problems[0].startswith("Read Needs: Could not find data source")
    assert "shared with the integration" in problems[0]
    assert problems[1] == "Daily Log: NOTION_DS_DAILY is not set. Run init-notion."


def test_require_schema_fails_fast_naming_the_property() -> None:
    fake, ids = set_up()
    del fake.sources[ids[CHARACTERS.env_key]]["properties"]["HoYo ID"]
    with pytest.raises(NotionSchemaError, match="'HoYo ID' is missing"):
        run(require_schema(fake, CHARACTERS, ids[CHARACTERS.env_key]))
