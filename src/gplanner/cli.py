"""Command line entry point: ``gplanner <command>``."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from gplanner.config import ConfigError, Settings
from gplanner.hoyolab.client import HoyolabClient, HoyolabError
from gplanner.models import CharacterSnapshot, RosterResult

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

_COLUMNS = ("Name", "Element", "Weapon type", "Rarity", "Lv", "Asc", "C", "N/S/B", "Weapon")


def _row(c: CharacterSnapshot) -> tuple[str, ...]:
    talents = f"{c.talents.normal}/{c.talents.skill}/{c.talents.burst}" if c.talents else "-"
    w = c.weapon
    return (
        c.name,
        c.element,
        c.weapon_type,
        str(c.rarity),
        str(c.level),
        f"{c.ascension}?" if c.ascension_ambiguous else str(c.ascension),
        str(c.constellation),
        talents,
        f"{w.name} Lv{w.level} R{w.refinement}",
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


async def _sync_roster(settings: Settings) -> RosterResult:
    client = HoyolabClient.from_settings(settings)
    return await client.fetch_roster()


def cmd_sync_roster(args: argparse.Namespace) -> int:
    if not args.dry_run:
        print(
            "sync-roster writes to Notion, which arrives in M2. Use --dry-run for now.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        settings = Settings.load()
        result = asyncio.run(_sync_roster(settings))
    except (ConfigError, HoyolabError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILED

    print(format_roster(result))
    print("Dry run: nothing was written.")
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gplanner", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    roster = commands.add_parser("sync-roster", help="Fetch the character roster from HoYoLAB.")
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
