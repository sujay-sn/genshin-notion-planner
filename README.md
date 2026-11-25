# genshin-notion-planner

Keeps a Notion planner in sync with a Genshin Impact account: who you're building, what materials they still need, and what to farm today on the Asia server. Each daily page has the official Teyvat Interactive Map embedded, so where to go is one tap away.

**Status:** design. No code yet. Start with [docs/DESIGN.md](docs/DESIGN.md).

## What's here

| Path | What it is |
|---|---|
| [docs/DESIGN.md](docs/DESIGN.md) | The design: architecture, Notion schema, time model, failure handling, build plan |
| [docs/endpoints.md](docs/endpoints.md) | Interactive map endpoints, captured and scrubbed |
| [tools/har_summary.py](tools/har_summary.py) | Turns a browser HAR export into a scrubbed endpoint summary |
| `.env.example` | Every config key the planner will need, with secrets left blank |
| [CLAUDE.md](CLAUDE.md) | Project rules for Claude Code: secrets, time handling, tests, git |

## Capturing endpoints

Record the map in Chrome DevTools (Network tab, "Preserve log" on), export a HAR, then:

```
python tools/har_summary.py path/to/capture.har --out docs/endpoints.md
```

The script hides cookies, tokens, UIDs, device IDs and names. Still review the output before committing it, and keep raw `.har` files out of the repo (they're gitignored).

## Secrets

Credentials go in `.env`, copied from `.env.example`. `.env`, `*.har` and `.cache/` are all gitignored. HoYoLAB cookies work like a login, so never commit them or paste them anywhere.

## Note

This uses unofficial HoYoLAB endpoints, through genshin.py and the interactive map's own API. It isn't affiliated with HoYoverse and is meant for personal use. Those endpoints can change with any game update.
