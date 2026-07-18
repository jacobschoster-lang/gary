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

Daily YouTube posting:
- Scheduling lives in GitHub Actions (`.github/workflows/daily-post.yml`), NOT
  the cloud VM (the VM is not always-on). It runs the daily post at 08:00
  America/New_York via a UTC cron pair (12:00 + 13:00) gated by
  `gary/jobs/schedule.py` for DST correctness.
- `gary/jobs/daily_post.py` dry-runs safely (writes a manifest to `out/`, no
  upload) unless `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`/
  `YOUTUBE_REFRESH_TOKEN` are set AND a rendered MP4 is provided via
  `--video-file` / `GARY_VIDEO_FILE`. Uploads need OAuth on the channel owner's
  account (an API key cannot upload).
- Video rendering lives in `gary/render/` (animated stick figures via Pillow +
  system `ffmpeg`). The daily job auto-renders an MP4 when `GARY_VIDEO_FILE` is
  unset. Rendering requires the `ffmpeg` binary (a runtime system dependency,
  pre-installed on the dev VM and installed by the workflow) — it is not a pip
  package. Videos currently have no audio; TTS narration is the next seam.

Non-obvious notes:
- Run all commands from the repo root. The `gary` package is imported directly
  (not pip-installed), so the working directory must be the repo root for
  imports and for locating `gary/templates/dashboard.html`.
- Generated transcripts are stored in-memory only (`gary.app._transcripts`); they
  reset whenever the server restarts.
- Real integrations plug into the `_draft_body` / `_fetch` seams in
  `gary/agents/`; those are the intended extension points for the open issues.
