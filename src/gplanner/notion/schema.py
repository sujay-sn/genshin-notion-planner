"""The four Notion databases (DESIGN.md section 6.1), init-notion and --check.

Every property is owned by the script, by you, or by Notion (formulas and
rollups). ``script_owned`` lists the only properties the script ever writes
to existing pages (section 6.2).

init-notion is safe to run again. Each data source ID is written to .env as
soon as that database exists, databases whose ID is already set are skipped,
and the finishing steps only add what's missing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from notion_client import AsyncClient

from gplanner.config import ConfigError, Settings
from gplanner.notion.client import NotionError, NotionSchemaError, call


def _title() -> dict[str, Any]:
    return {"title": {}}


def _text() -> dict[str, Any]:
    return {"rich_text": {}}


def _number() -> dict[str, Any]:
    return {"number": {"format": "number"}}


def _select(*options: str) -> dict[str, Any]:
    # An explicit options list: the docs don't promise `{"select": {}}` is accepted.
    # Pages create any other option on first write.
    return {"select": {"options": [{"name": name} for name in options]}}


def _multi_select() -> dict[str, Any]:
    return {"multi_select": {"options": []}}


def _checkbox() -> dict[str, Any]:
    return {"checkbox": {}}


def _date() -> dict[str, Any]:
    return {"date": {}}


def _url() -> dict[str, Any]:
    return {"url": {}}


def _type_of(config: Mapping[str, Any]) -> str:
    (prop_type,) = (key for key in config if key not in ("name", "type", "id"))
    return prop_type


@dataclass(frozen=True)
class DatabaseSpec:
    title: str
    settings_attr: str
    env_key: str
    # Created with the database, in the order shown in Notion.
    properties: Mapping[str, Mapping[str, Any]]
    script_owned: frozenset[str]
    # Relations, rollups and formulas. Their configs depend on other databases'
    # IDs, so only the type is listed here, for --check.
    linked: Mapping[str, str] = field(default_factory=dict)

    def expected_types(self) -> dict[str, str]:
        types = {name: _type_of(config) for name, config in self.properties.items()}
        types.update(self.linked)
        return types

    def property_type(self, name: str) -> str:
        return self.expected_types()[name]


CHARACTERS = DatabaseSpec(
    title="Characters",
    settings_attr="notion_ds_characters",
    env_key="NOTION_DS_CHARACTERS",
    properties={
        # Script-owned
        "Name": _title(),
        "HoYo ID": _number(),
        "Element": _select(),
        "Weapon type": _select(),
        "Rarity": _select(),
        "Level": _number(),
        "Ascension": _number(),
        "Constellation": _number(),
        "Normal": _number(),
        "Skill": _number(),
        "Burst": _number(),
        "Weapon": _text(),
        "Last synced": _date(),
        # Yours
        "Building": _checkbox(),
        "Priority": _number(),
        "Ascended at cap": _checkbox(),
        "Target level": _number(),
        "Target Normal": _number(),
        "Target Skill": _number(),
        "Target Burst": _number(),
    },
    script_owned=frozenset(
        {
            "Name",
            "HoYo ID",
            "Element",
            "Weapon type",
            "Rarity",
            "Level",
            "Ascension",
            "Constellation",
            "Normal",
            "Skill",
            "Burst",
            "Weapon",
            "Last synced",
        }
    ),
)

MATERIALS = DatabaseSpec(
    title="Materials",
    settings_attr="notion_ds_materials",
    env_key="NOTION_DS_MATERIALS",
    properties={
        # Script-owned
        "Name": _title(),
        "HoYo item ID": _number(),
        "Type": _select(),
        "Source": _text(),
        "Region": _select(),
        "Farm days": _multi_select(),
        "Resin cost": _number(),
        "Spawn points": _number(),
        "Map link": _url(),
        # Yours
        "Owned": _number(),
        "Last collected": _date(),
    },
    script_owned=frozenset(
        {
            "Name",
            "HoYo item ID",
            "Type",
            "Source",
            "Region",
            "Farm days",
            "Resin cost",
            "Spawn points",
            "Map link",
        }
    ),
    # Notion's: the reverse side of Needs.Material, and what's built on it.
    linked={"Needs": "relation", "Needed": "rollup", "Short by": "formula", "Back at": "formula"},
)

NEEDS = DatabaseSpec(
    title="Needs",
    settings_attr="notion_ds_needs",
    env_key="NOTION_DS_NEEDS",
    properties={
        "Key": _title(),
        "Quantity": _number(),
        # Character and Material relations need the other data source IDs, so
        # they're added when the database is created (see _create_properties).
    },
    script_owned=frozenset({"Key", "Character", "Material", "Quantity"}),
    linked={"Character": "relation", "Material": "relation"},
)

DAILY = DatabaseSpec(
    title="Daily Log",
    settings_attr="notion_ds_daily",
    env_key="NOTION_DS_DAILY",
    properties={
        # Script-owned
        "Title": _title(),
        "Server day": _date(),
        "Kind": _select("Daily", "Weekly"),
        "Resin at sync": _number(),
        "Resin full at": _date(),
        "Commissions": _text(),
        "Weekly boss discounts left": _number(),
        "Synced at": _date(),
        # Yours
        "Notes": _text(),
    },
    script_owned=frozenset(
        {
            "Title",
            "Server day",
            "Kind",
            "Resin at sync",
            "Resin full at",
            "Commissions",
            "Weekly boss discounts left",
            "Synced at",
        }
    ),
)

# Creation order matters: Needs relates to Characters and Materials.
DATABASES: tuple[DatabaseSpec, ...] = (CHARACTERS, MATERIALS, NEEDS, DAILY)

NEEDS_RELATION = "Needs"


def short_by_formula() -> str:
    # A blank Owned counts as 0.
    return 'max(prop("Needed") - if(empty(prop("Owned")), 0, prop("Owned")), 0)'


def back_at_formula(respawn_hours: int) -> str:
    return f'dateAdd(prop("Last collected"), {respawn_hours}, "hours")'


def _create_properties(spec: DatabaseSpec, ids: Mapping[str, str | None]) -> dict[str, Any]:
    properties = {name: dict(config) for name, config in spec.properties.items()}
    if spec is NEEDS:
        properties["Character"] = {
            "relation": {
                "data_source_id": ids[CHARACTERS.env_key],
                "type": "single_property",
                "single_property": {},
            }
        }
        properties["Material"] = {
            "relation": {
                "data_source_id": ids[MATERIALS.env_key],
                "type": "dual_property",
                "dual_property": {"synced_property_name": NEEDS_RELATION},
            }
        }
    return properties


# init-notion

SaveIds = Callable[[Mapping[str, str]], None]


def configured_ids(settings: Settings) -> dict[str, str | None]:
    return {spec.env_key: getattr(settings, spec.settings_attr) for spec in DATABASES}


async def _data_source_id(notion: AsyncClient, database: Mapping[str, Any], title: str) -> str:
    sources = database.get("data_sources") or []
    if not sources:
        # The create response may be partial. Fetch the database to find its source.
        database = await call(
            f"{title}: read new database", notion.databases.retrieve(database_id=database["id"])
        )
        sources = database.get("data_sources") or []
    if len(sources) != 1:
        raise NotionError(f"{title}: expected one data source, found {len(sources)}")
    return sources[0]["id"]


async def init_workspace(
    notion: AsyncClient,
    settings: Settings,
    save_ids: SaveIds,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Create whatever is missing of the four databases. Returns what it did."""
    if not settings.notion_parent_page_id:
        raise ConfigError("Missing in .env: NOTION_PARENT_PAGE_ID")
    ids = configured_ids(settings)
    log: list[str] = []
    verb = "Would create" if dry_run else "Created"

    for spec in DATABASES:
        if ids[spec.env_key]:
            log.append(f"{spec.title}: already set up ({spec.env_key}), skipped")
            continue
        properties = _create_properties(spec, {k: v or "<new>" for k, v in ids.items()})
        if dry_run:
            log.append(f"{verb} {spec.title} with {len(properties)} properties")
            ids[spec.env_key] = "<new>"
            continue
        database = await call(
            f"Create {spec.title}",
            notion.databases.create(
                parent={"type": "page_id", "page_id": settings.notion_parent_page_id},
                title=[{"type": "text", "text": {"content": spec.title}}],
                initial_data_source={"properties": properties},
            ),
        )
        ds_id = await _data_source_id(notion, database, spec.title)
        ids[spec.env_key] = ds_id
        save_ids({spec.env_key: ds_id})
        log.append(f"{verb} {spec.title} with {len(properties)} properties ({spec.env_key})")

    log.extend(await _finish_materials(notion, settings, ids, dry_run=dry_run))
    return log


async def _finish_materials(
    notion: AsyncClient,
    settings: Settings,
    ids: Mapping[str, str | None],
    *,
    dry_run: bool,
) -> list[str]:
    """Name the reverse relation, then add the rollup and formulas, if missing."""
    materials_id = ids[MATERIALS.env_key]
    needs_id = ids[NEEDS.env_key]
    assert materials_id and needs_id
    formulas = {
        "Short by": short_by_formula(),
        "Back at": back_at_formula(settings.specialty_respawn_hours),
    }

    if materials_id == "<new>":  # dry run of a fresh setup: nothing to read yet
        return [
            f"Would add to Materials: {NEEDS_RELATION} relation name, Needed rollup, "
            f"Short by and Back at formulas (respawn {settings.specialty_respawn_hours} hours)"
        ]

    source = await call("Read Materials", notion.data_sources.retrieve(data_source_id=materials_id))
    properties: dict[str, Any] = source["properties"]
    log: list[str] = []

    if NEEDS_RELATION not in properties:
        reverse = [
            name
            for name, prop in properties.items()
            if prop["type"] == "relation"
            and _same_id(prop["relation"].get("data_source_id"), needs_id)
        ]
        if dry_run and needs_id == "<new>":
            log.append(f"Would name Materials' relation to Needs {NEEDS_RELATION!r}")
        elif len(reverse) != 1:
            raise NotionSchemaError(
                f"Materials: expected one relation back to Needs, found {len(reverse)}. "
                "Check the Needs database's Material property."
            )
        else:
            if not dry_run:
                await call(
                    "Rename Materials relation",
                    notion.data_sources.update(
                        data_source_id=materials_id,
                        properties={reverse[0]: {"name": NEEDS_RELATION}},
                    ),
                )
            log.append(
                f"{'Would rename' if dry_run else 'Renamed'} Materials relation "
                f"{reverse[0]!r} to {NEEDS_RELATION!r}"
            )

    if "Needed" not in properties:
        if not dry_run:
            await call(
                "Add Materials Needed rollup",
                notion.data_sources.update(
                    data_source_id=materials_id,
                    properties={
                        "Needed": {
                            "rollup": {
                                "relation_property_name": NEEDS_RELATION,
                                "rollup_property_name": "Quantity",
                                "function": "sum",
                            }
                        }
                    },
                ),
            )
        log.append(
            f"{'Would add' if dry_run else 'Added'} Materials Needed rollup (sum of Needs quantity)"
        )

    missing = {name: expr for name, expr in formulas.items() if name not in properties}
    if missing:
        if not dry_run:
            await call(
                "Add Materials formulas",
                notion.data_sources.update(
                    data_source_id=materials_id,
                    properties={
                        name: {"formula": {"expression": expr}} for name, expr in missing.items()
                    },
                ),
            )
        log.append(
            f"{'Would add' if dry_run else 'Added'} Materials formulas: {', '.join(missing)}"
        )

    if not log:
        log.append("Materials: relation, rollup and formulas already in place")
    return log


def _same_id(a: str | None, b: str | None) -> bool:
    return bool(a and b) and a.replace("-", "") == b.replace("-", "")


# --check


def schema_problems(spec: DatabaseSpec, properties: Mapping[str, Any]) -> list[str]:
    """What's missing or has the wrong type, by name, in one data source's schema."""
    problems = []
    for name, expected in spec.expected_types().items():
        prop = properties.get(name)
        if prop is None:
            problems.append(f"{spec.title}: property {name!r} is missing (renamed or deleted?)")
        elif prop["type"] != expected:
            problems.append(
                f"{spec.title}: property {name!r} is {prop['type']}, expected {expected}"
            )
    return problems


async def check_database(notion: AsyncClient, spec: DatabaseSpec, ds_id: str | None) -> list[str]:
    if not ds_id:
        return [f"{spec.title}: {spec.env_key} is not set. Run init-notion."]
    try:
        source = await call(
            f"Read {spec.title}", notion.data_sources.retrieve(data_source_id=ds_id)
        )
    except NotionError as exc:
        return [f"{exc}. Is the database still there and shared with the integration?"]
    return schema_problems(spec, source["properties"])


async def check_workspace(notion: AsyncClient, settings: Settings) -> list[str]:
    ids = configured_ids(settings)
    problems: list[str] = []
    for spec in DATABASES:
        problems.extend(await check_database(notion, spec, ids[spec.env_key]))
    return problems


async def require_schema(notion: AsyncClient, spec: DatabaseSpec, ds_id: str | None) -> str:
    """Fail fast, naming the property, if a database isn't usable (DESIGN.md section 11)."""
    problems = await check_database(notion, spec, ds_id)
    if problems:
        raise NotionSchemaError(
            "; ".join(problems) + ". Run `gplanner init-notion --check` for the full list."
        )
    assert ds_id
    return ds_id
