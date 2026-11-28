"""An in-memory stand-in for notion_client.AsyncClient.

It keeps data source schemas and pages, so a test can run init-notion or a
roster sync, then read back exactly what a real query would return and run
again. Every call is recorded, which is how the tests check that a second run
makes zero writes and that your properties never appear in a payload.

It mimics the awkward parts the docs leave open (DESIGN.md section 6.1): the
reverse side of a dual relation gets Notion's own name, not the one asked for,
and a create response can leave out the data source list.
"""

from __future__ import annotations

import itertools
from typing import Any

import httpx
from notion_client.errors import APIErrorCode, APIResponseError

WRITE_METHODS = {
    "databases.create",
    "data_sources.update",
    "pages.create",
    "pages.update",
}


def not_found(what: str) -> APIResponseError:
    return APIResponseError(
        APIErrorCode.ObjectNotFound, 404, f"Could not find {what}.", httpx.Headers(), ""
    )


def _prop_type(config: dict[str, Any]) -> str:
    (prop_type,) = (k for k in config if k not in ("name", "type", "id"))
    return prop_type


def _empty(prop_type: str) -> Any:
    return {
        "title": [],
        "rich_text": [],
        "multi_select": [],
        "checkbox": False,
    }.get(prop_type)


def _to_read(prop_type: str, written: Any) -> dict[str, Any]:
    """A written property value as a query would return it."""
    if prop_type in ("title", "rich_text"):
        value: Any = [{"plain_text": part["text"]["content"]} for part in written]
    else:
        value = written
    return {"type": prop_type, prop_type: value}


class _Databases:
    def __init__(self, fake: FakeNotion) -> None:
        self.fake = fake

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        self.fake.record("databases.create", kwargs)
        db_id = f"db-{next(self.fake.ids)}"
        ds_id = f"ds-{next(self.fake.ids)}"
        title = kwargs["title"][0]["text"]["content"]
        properties = {}
        for name, config in kwargs["initial_data_source"]["properties"].items():
            prop_type = _prop_type(config)
            properties[name] = {"type": prop_type, prop_type: config[prop_type]}
            if prop_type == "relation" and config["relation"]["type"] == "dual_property":
                # The docs don't say whether synced_property_name is honoured on
                # create. By default the fake gives Notion's own name instead.
                target = self.fake.sources[config["relation"]["data_source_id"]]
                synced = config["relation"]["dual_property"].get("synced_property_name")
                reverse = synced if self.fake.honor_synced_name else None
                target["properties"][reverse or f"Related to {title} ({name})"] = {
                    "type": "relation",
                    "relation": {"data_source_id": ds_id, "type": "dual_property"},
                }
        self.fake.sources[ds_id] = {"title": title, "properties": properties}
        self.fake.databases_by_id[db_id] = ds_id
        if self.fake.partial_create:
            return {"object": "database", "id": db_id}
        return {"object": "database", "id": db_id, "data_sources": [{"id": ds_id, "name": title}]}

    async def retrieve(self, database_id: str) -> dict[str, Any]:
        self.fake.record("databases.retrieve", {"database_id": database_id})
        ds_id = self.fake.databases_by_id[database_id]
        return {"object": "database", "id": database_id, "data_sources": [{"id": ds_id}]}


class _DataSources:
    def __init__(self, fake: FakeNotion) -> None:
        self.fake = fake

    def _source(self, data_source_id: str) -> dict[str, Any]:
        if data_source_id not in self.fake.sources:
            raise not_found(f"data source with ID: {data_source_id}")
        return self.fake.sources[data_source_id]

    async def retrieve(self, data_source_id: str) -> dict[str, Any]:
        self.fake.record("data_sources.retrieve", {"data_source_id": data_source_id})
        source = self._source(data_source_id)
        return {"object": "data_source", "id": data_source_id, "properties": source["properties"]}

    async def update(self, data_source_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        self.fake.record(
            "data_sources.update", {"data_source_id": data_source_id, "properties": properties}
        )
        source = self._source(data_source_id)
        for name, config in properties.items():
            if set(config) == {"name"}:
                source["properties"][config["name"]] = source["properties"].pop(name)
            else:
                prop_type = _prop_type(config)
                source["properties"][name] = {"type": prop_type, prop_type: config[prop_type]}
        return {"object": "data_source", "id": data_source_id}

    async def query(self, data_source_id: str, start_cursor: str | None = None) -> dict[str, Any]:
        self.fake.record("data_sources.query", {"data_source_id": data_source_id})
        self._source(data_source_id)
        pages = [p for p in self.fake.pages_by_id.values() if p["data_source_id"] == data_source_id]
        return {"results": pages, "has_more": False, "next_cursor": None}


class _Pages:
    def __init__(self, fake: FakeNotion) -> None:
        self.fake = fake

    async def create(self, parent: dict[str, Any], properties: dict[str, Any]) -> dict[str, Any]:
        self.fake.record("pages.create", {"parent": parent, "properties": properties})
        ds_id = parent["data_source_id"]
        schema = self.fake.sources[ds_id]["properties"]
        page_id = f"page-{next(self.fake.ids)}"
        stored = {
            name: {"type": p["type"], p["type"]: _empty(p["type"])} for name, p in schema.items()
        }
        page = {"id": page_id, "data_source_id": ds_id, "properties": stored}
        self.fake.pages_by_id[page_id] = page
        self.fake.write_props(page, properties)
        return {"object": "page", "id": page_id}

    async def update(self, page_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        self.fake.record("pages.update", {"page_id": page_id, "properties": properties})
        self.fake.write_props(self.fake.pages_by_id[page_id], properties)
        return {"object": "page", "id": page_id}


class FakeNotion:
    def __init__(self, *, partial_create: bool = False, honor_synced_name: bool = False) -> None:
        self.partial_create = partial_create
        self.honor_synced_name = honor_synced_name
        self.ids = itertools.count(1)
        self.sources: dict[str, dict[str, Any]] = {}
        self.databases_by_id: dict[str, str] = {}
        self.pages_by_id: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.databases = _Databases(self)
        self.data_sources = _DataSources(self)
        self.pages = _Pages(self)
        self.closed = False

    def record(self, method: str, payload: dict[str, Any]) -> None:
        self.calls.append((method, payload))

    def writes(self) -> list[tuple[str, dict[str, Any]]]:
        return [call for call in self.calls if call[0] in WRITE_METHODS]

    def write_props(self, page: dict[str, Any], properties: dict[str, Any]) -> None:
        for name, value in properties.items():
            (prop_type,) = value
            page["properties"][name] = _to_read(prop_type, value[prop_type])

    def set_property(self, page_id: str, name: str, written: dict[str, Any]) -> None:
        """Change a page the way you would in Notion, without recording a call."""
        self.write_props(self.pages_by_id[page_id], {name: written})

    def add_source(self, title: str, properties: dict[str, str]) -> str:
        """A data source with the given property names and types, for --check tests."""
        ds_id = f"ds-{next(self.ids)}"
        self.sources[ds_id] = {
            "title": title,
            "properties": {name: {"type": t, t: {}} for name, t in properties.items()},
        }
        return ds_id

    async def aclose(self) -> None:
        self.closed = True
