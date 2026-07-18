# AGENTS.md

## Cursor Cloud specific instructions

`gary` is a Python 3.12 + FastAPI starter for an automated finance-content
platform (agents + dashboard). Agents currently use deterministic, offline
logic, so everything runs and tests without any API keys or external services.

The update script provisions `.venv/` and installs `requirements.txt`. Use that
interpreter directly (`.venv/bin/...`); the venv is not auto-activated.

Standard commands (see `README.md` for details):
- Run dev server: `.venv/bin/uvicorn gary.app:app --reload --host 0.0.0.0 --port 8000`
- Lint: `.venv/bin/ruff check .`
- Test: `.venv/bin/pytest -q`

Non-obvious notes:
- Run all commands from the repo root. The `gary` package is imported directly
  (not pip-installed), so the working directory must be the repo root for
  imports and for locating `gary/templates/dashboard.html`.
- Generated transcripts are stored in-memory only (`gary.app._transcripts`); they
  reset whenever the server restarts.
- Real integrations plug into the `_draft_body` / `_fetch` seams in
  `gary/agents/`; those are the intended extension points for the open issues.
