# AGENTS.md

## Cursor Cloud specific instructions

`gary` is a Python 3.12 + FastAPI starter for an automated finance-content
platform (agents + dashboard). Agents currently use deterministic, offline
logic, so everything runs and tests without any API keys or external services.

The update script provisions `.venv/` and installs `requirements.txt`. Use that
interpreter directly (`.venv/bin/...`); the venv is not auto-activated.

Cloud agent install is defined in `.cursor/environment.json` and runs
`bash scripts/install.sh` (creates `.venv/`, installs deps). Run the same script
locally if needed. **Do not** put natural-language prompts in the Cursor
dashboard install field — it must be valid shell; repo `environment.json` takes
precedence when present.

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

Real estate:
- `gary/realestate/` powers the dashboard "Land & homes for sale" card and
  `GET /api/realestate` (radius + min acres + max price). Live listings need
  `RENTCAST_API_KEY` (free tier); without it, it returns a labeled sample set.
  Radius search centers on coords in `CITY_COORDS` (Cincinnati and a few metros);
  acreage/price are filtered client-side (RentCast returns lotSize in sqft).

Trading bot (paper):
- `gary/trading/` powers the dashboard "Trading" tab and `/api/trading/*`
 (`status`, `run`, `reset`). It's a **paper** bot (`PaperBroker`) — no real
 money — blending momentum, price-history (SMA crossover), and mean-reversion
 signals with risk rules (30% take-profit, stop-loss, and skimming 50% of
 realized profit into a lower-risk reserve). Defaults: $10k start, 2× goal.
- `POST /api/trading/run` runs a from-scratch backtest over the last N days and
 persists the resulting account to `finance_data/trading.json` (gitignored;
 override with `GARY_TRADING_FILE`).
- `POST /api/trading/optimize` (`gary/trading/optimize.py`) grid-searches the
 tunable `BotConfig` knobs (exit style incl. trailing stops, position size,
 add-ons/pyramiding, entry sensitivity), scores each by drawdown-adjusted final
 equity, then applies + persists the best config. It fetches each symbol's
 price series once and reuses it across all candidates (don't re-fetch per
 candidate). Backtests are deterministic offline, so the optimizer is too.
- Prices come from `gary/trading/prices.py` (Yahoo/CoinGecko via
 `gary.data.http`) with a **deterministic synthetic fallback** seeded per
 symbol, so simulations run offline and tests are reproducible (the offline
 fixture in `tests/conftest.py` forces the synthetic path). Strategies in
 `gary/trading/strategies.py` are pure functions over a close series.
- Going live is an env-gated seam: `gary/trading/robinhood.py`
 (`RobinhoodCryptoBroker.from_env`, needs `ROBINHOOD_API_KEY`/
 `ROBINHOOD_PRIVATE_KEY` + `TRADING_LIVE=1`). Order placement is intentionally
 unimplemented — Robinhood has no official equities API; only the official
 Crypto API is safe to wire in. Keep the bot on paper until then.

Non-obvious notes:
- Run all commands from the repo root. The `gary` package is imported directly
  (not pip-installed), so the working directory must be the repo root for
  imports and for locating `gary/templates/dashboard.html`.
- Generated transcripts are stored in-memory only (`gary.app._transcripts`); they
  reset whenever the server restarts.
- Real integrations plug into the `_draft_body` / `_fetch` seams in
  `gary/agents/`; those are the intended extension points for the open issues.
