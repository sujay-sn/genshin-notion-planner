"""Command line entry point: ``gplanner <command>``."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import Any

from gplanner.clock import Clock
from gplanner.config import ConfigError, Settings, save_env_values
from gplanner.hoyolab.client import HoyolabClient, HoyolabError
from gplanner.models import CharacterSnapshot, RosterResult
from gplanner.notion.client import NotionError, make_client
from gplanner.notion.repo import RosterPlan, apply_plan, fetch_pages, plan_roster
from gplanner.notion.schema import CHARACTERS, check_workspace, init_workspace, require_schema

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

_COLUMNS = ("Name", "Element", "Weapon type", "Rarity", "Lv", "Asc", "C", "N/S/B", "Weapon")


def _row(c: CharacterSnapshot) -> tuple[str, ...]:
    talents = f"{c.talents.normal}/{c.talents.skill}/{c.talents.burst}" if c.talents else "-"
    return (
        c.name,
        c.element,
        c.weapon_type,
        str(c.rarity),
        str(c.level),
        f"{c.ascension}?" if c.ascension_ambiguous else str(c.ascension),
        str(c.constellation),
        talents,
        c.weapon.label,
    )


def format_roster(result: RosterResult) -> str:
    """The roster as a plain-text table, five-stars and high levels first."""
    ordered = sorted(result.characters, key=lambda c: (-c.rarity, -c.level, c.name))
    rows = [_COLUMNS, *(_row(c) for c in ordered)]
    widths = [max(len(row[i]) for row in rows) for i in range(len(_COLUMNS))]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    ]
    lines.insert(1, "  ".join("-" * width for width in widths))
    lines.append("")
    lines.append(f"{len(ordered)} characters.")
    if any(c.ascension_ambiguous for c in ordered):
        lines.append(
            "Asc with ?: HoYoLAB doesn't report ascension. At a level cap the character "
            "may already have ascended, so the lower value is shown."
        )
    return "\n".join(lines)


def _show(value: Any) -> str:
    return "blank" if value in (None, "") else str(value)


def format_plan(plan: RosterPlan, *, dry_run: bool) -> str:
    """Creates and updates, one line per page, with what changed."""
    lines = []
    for write in plan.creates:
        lines.append(f"+ {write.name}")
    for write in plan.updates:
        changed = ", ".join(
            f"{name} {_show(old)} -> {_show(new)}" for name, (old, new) in write.changes.items()
        )
        lines.append(f"~ {write.name}: {changed}")
    verb = "to create" if dry_run else "created"
    verb_update = "to update" if dry_run else "updated"
    lines.append(
        f"Characters: {len(plan.creates)} {verb}, {len(plan.updates)} {verb_update}, "
        f"{plan.unchanged} unchanged."
    )
    return "\n".join(lines)


def _report(problems: Sequence[str], label: str) -> None:
    for line in problems:
        print(f"{label}: {line}", file=sys.stderr)


async def _sync_roster(settings: Settings, *, dry_run: bool) -> tuple[RosterResult, RosterPlan]:
    notion = make_client(settings)
    try:
        # Check Notion first: it's cheap, and a broken schema should stop the run
        # before any HoYoLAB requests.
        ds_id = await require_schema(notion, CHARACTERS, settings.notion_ds_characters)
        roster = await HoyolabClient.from_settings(settings).fetch_roster()
        pages = await fetch_pages(notion, ds_id)
        synced_at = Clock(settings).now_utc().isoformat(timespec="seconds")
        plan = plan_roster(roster.characters, pages, synced_at)
        if not dry_run:
            await apply_plan(notion, ds_id, plan, sleep=asyncio.sleep)
        return roster, plan
    finally:
        await notion.aclose()


def cmd_sync_roster(args: argparse.Namespace) -> int:
    try:
        settings = Settings.load()
        roster, plan = asyncio.run(_sync_roster(settings, dry_run=args.dry_run))
    except (ConfigError, HoyolabError, NotionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILED

    print(format_plan(plan, dry_run=args.dry_run))
    if args.dry_run:
        print("Dry run: nothing was written.")
    for note in roster.notes:
        print(f"note: {note}")
    _report([*roster.warnings, *plan.warnings], "warning")
    return EXIT_OK


async def _init_notion(settings: Settings, *, check: bool, dry_run: bool) -> list[str]:
    notion = make_client(settings)
    try:
        if check:
            return await check_workspace(notion, settings)
        for line in await init_workspace(notion, settings, save_env_values, dry_run=dry_run):
            print(line)
        if dry_run:
            return []
        # Re-read .env for the IDs just written, then confirm the result.
        return await check_workspace(notion, Settings.load())
    finally:
        await notion.aclose()


def cmd_init_notion(args: argparse.Namespace) -> int:
    try:
        settings = Settings.load()
        problems = asyncio.run(_init_notion(settings, check=args.check, dry_run=args.dry_run))
    except (ConfigError, NotionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILED

    if problems:
        _report(problems, "problem")
        print(
            "Fix each property in Notion (rename it back or recreate it with that type), "
            "or run init-notion to add anything missing from Materials.",
            file=sys.stderr,
        )
        return EXIT_FAILED
    if args.dry_run:
        print("Dry run: nothing was written.")
    else:
        print("All four databases match the expected schema.")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gplanner", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser(
        "init-notion", help="Create the four Notion databases under NOTION_PARENT_PAGE_ID."
    )
    mode = init.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="Only check the databases' properties. No writes."
    )
    mode.add_argument(
        "--dry-run", action="store_true", help="Print what would be created and write nothing."
    )
    init.set_defaults(func=cmd_init_notion)

    roster = commands.add_parser(
        "sync-roster", help="Sync the character roster from HoYoLAB into Notion."
    )
    roster.add_argument(
        "--dry-run", action="store_true", help="Print what would change and write nothing."
    )
    roster.set_defaults(func=cmd_sync_roster)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Weapon and character names can fall outside a Windows console's code page.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")

    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
