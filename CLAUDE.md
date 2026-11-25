# CLAUDE.md

## Source of truth
docs/DESIGN.md is the design. Read it before starting any task. If the code needs to
differ from it, update DESIGN.md in the same commit and tell me why.
docs/endpoints.md describes the unofficial map endpoints.

## Hard rules
- Never read, print, or commit .env or any *.har file. Secrets reach the code only
  through config.py. Never ask me to paste cookies or tokens into the chat.
- Only src/gplanner/hoyolab/ and src/gplanner/notion/ make network calls.
  planner/ and clock.py are pure and make no network calls.
- All date and time logic lives in clock.py. Compare in UTC or server time, and
  convert to local only for display. Offsets and zones come from config.
- Notion ownership rule (DESIGN.md 6.2): the script writes only script-owned
  properties. Never overwrite a property I own.
- genshin.py changes monthly. Before using any genshin.py method, check the installed
  version's source or docs. Don't guess method names.
- Don't invent game data. If domain_schedule.yaml or overrides need entries you're
  not sure of, especially for regions after mid-2026, mark them TODO and ask me.

## Tests
- pytest, no live API calls by default. Live tests get @pytest.mark.live and are
  skipped unless I run them on purpose.
- Fixtures must be scrubbed: no UIDs, cookies, device IDs or nicknames.

## Git
- One milestone per branch, small commits, conventional commit messages.
- Run git status and show me the staged files before every commit.
- Never push. The repo is public, so I push after I've reviewed the changes.

## Commands
- pip install -e ".[dev]"
- pytest
- ruff check . && ruff format --check .

## Done means
The "Done when" column for the milestone in DESIGN.md section 16 is met, tests and
ruff pass, and any open question from section 15 you resolved is updated there.
