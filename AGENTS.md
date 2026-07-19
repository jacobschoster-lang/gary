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
  system `ffmpeg`, with gTTS voiceover). The daily job auto-renders an MP4 when
  `GARY_VIDEO_FILE` is unset. Rendering requires the `ffmpeg` binary (a runtime
  system dependency, pre-installed on the dev VM and installed by the workflow) —
  it is not a pip package.
- Live data (`gary/data/`) and gTTS voiceover both need network. Everything
  fails soft: agents fall back to sample data and video falls back to silent, so
  the app/tests never break offline. Tests force this offline path via the
  autouse fixture in `tests/conftest.py` (patches `gary.data.http` +
  `gtts.gTTS`); when adding data/TTS code keep it patchable there and keep calls
  going through `gary.data.http` so they stay deterministic in tests.
- Live agents make network calls per request (short timeouts + 60s cache in
  `gary/data/http.py`). Construct agents/pipeline with `use_live=False` for
  fully offline/deterministic behavior.
- LLM scripting (`gary/agents/llm.py`) activates only when `OPENAI_API_KEY` is
  set and must return the four renderer headings (`Hook`, `The Data`,
  `Analysis`, `Call To Action`) or it's discarded for the deterministic script.
  Use `TranscriptAgent(use_llm=False)` to disable. The offline test fixture
  patches `gary.agents.llm._chat_completion` so the LLM never runs in tests.
- Video captions are per-sentence (subtitle-style): the renderer splits each
  scene's narration into sentences and gives each its own timed sub-segment, so
  caption text must stay aligned with the narration text.
- No-key local LLM for dev/sandbox: run Ollama and set `OPENAI_BASE_URL=`
  `http://localhost:11434/v1`, `OPENAI_API_KEY=ollama`, `OPENAI_MODEL=llama3.2:3b`.
  Gotcha on this cloud VM: Ollama's AVX-512/AMX CPU backends segfault ("llama-
  server terminated: signal: segmentation fault"). Fix by moving the AVX-512
  variants out of `/usr/local/lib/ollama/` (keep `libggml-cpu-haswell.so` = AVX2)
  and restarting `ollama serve`, which forces the stable AVX2 path.

Personal finance:
- `gary/finance/` powers the dashboard "My finances" + "Cash flow" cards
  (net worth, debt payoff, health advice, and CSV/image transaction import).
- Data persists to `finance_data/profile.json` (gitignored; override with
  `GARY_FINANCE_FILE`). Importing a bank CSV or image derives monthly
  income/expenses automatically.
- Image ("snapshot") import uses OCR via the `tesseract` system binary
  (pre-installed on the dev VM; `pytesseract` is the Python wrapper) — CSV is
  more accurate. File uploads need `python-multipart`.
- Plaid bank aggregation (`gary/finance/plaid.py`) is enabled only when
  `PLAID_CLIENT_ID`/`PLAID_SECRET` are set (`PLAID_ENV` defaults to `sandbox`;
  test login `user_good`/`pass_good`). The access token persists to
  `finance_data/plaid.json` (gitignored). Endpoints degrade to HTTP 400 when
  unconfigured; the connector uses httpx directly (no Plaid SDK), so tests mock
  `gary.finance.plaid.httpx.post`.

Non-obvious notes:
- Run all commands from the repo root. The `gary` package is imported directly
  (not pip-installed), so the working directory must be the repo root for
  imports and for locating `gary/templates/dashboard.html`.
- Generated transcripts are stored in-memory only (`gary.app._transcripts`); they
  reset whenever the server restarts.
- Real integrations plug into the `_draft_body` / `_fetch` seams in
  `gary/agents/`; those are the intended extension points for the open issues.
