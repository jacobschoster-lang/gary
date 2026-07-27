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
- Realism: fills include transaction cost + slippage (`fee_bps`/`slippage_bps`
 on `BotConfig`/`PaperBroker`; realized P&L is net of round-trip costs), and the
 engine uses **next-bar-open execution** — `TradingBot._run` decides on closes
 strictly before the fill bar to avoid look-ahead bias. Bare `PaperBroker()`
 defaults costs to 0 so direct unit tests stay exact; the engine wires in
 `BotConfig` costs.
- `gary/trading/metrics.py` holds pure metric functions (Sharpe, Sortino,
 Calmar, win rate, profit factor, turnover, drawdown); every report embeds a
 `metrics` block via `metrics.summarize(equity_series, fills)`.
- Portfolio/signal modes (all on `BotConfig`, off by default so `per_symbol`
 behavior is unchanged): `selection_mode="cross_sectional"` (rank the universe by
 momentum, hold top-N, rotate), `selection_mode="long_short"` (long top-N, short
 bottom-N — market-neutral, uses `PaperBroker.short`/`cover` with signed positions
 and per-bar `borrow_bps`), `regime_ma` (trend filter with regime exits), and
 `vol_target` (volatility-targeted sizing in `risk.position_notional`).
 `rebalance_every` throttles turnover (risk exits still run every bar; rotation/
 entries only every N bars). `TradingBot.warmup()` widens history to the longest
 lookback in use, so more history is fetched when these are enabled.
- `gary/trading/selection.py` provides robust-selection stats (robustness =
 mean − stdev across folds; deflated Sharpe for multiple-testing). The optimizer
 chooses the config on **train** robustness only, then reports out-of-sample.
- `selection_mode="buy_hold"` is a regime-filtered, vol-targeted, low-turnover
 "smart buy & hold" baseline (holds the eligible universe). It's in the grid; on
 recent data the robust optimizer often picks it — consistent with the honest
 finding that active trading rarely beats holding here.
- Forward paper trading (distinct from the from-scratch backtest): `TradingBot.
 step_live()` advances the **persisted** account one step at the latest prices;
 `TradingStore.record_equity()` keeps a de-duped daily equity history (exposed at
 `/api/trading/status` as `forward_equity`). `python -m gary.jobs.trade_daily`
 runs one forward step for a scheduler (paper-only, safe; writes a manifest to
 `out/`). It never sends real orders.
- Live via Robinhood MCP (`gary/trading/robinhood_mcp.py`, preferred live path):
 `RobinhoodMcpBroker` routes the bot's orders to Robinhood's official MCP trading
 server (`https://agent.robinhood.com/mcp/trading`) as tool calls. It implements
 the same `Broker` surface as `PaperBroker`, is gated on `ROBINHOOD_MCP_TOKEN` +
 `TRADING_LIVE=1`, and takes an **injectable `caller(tool, args)`** (tests use a
 fake; a real run uses the built-in JSON-RPC-over-HTTP client, or a caller that
 forwards to Cursor's `CallMcpTool`). Tool names are placeholders overridable via
 `ROBINHOOD_MCP_TOOL_*` — **confirm them with `GetMcpTools` after the MCP server
 is added + authenticated** (cloud agents need it authenticated in the Cursor
 desktop IDE; only `cursor-cloud` MCP is present by default). Engine→live routing
 is still not wired; the bot stays on `PaperBroker` until deliberately switched.
- Live crypto seam (`gary/trading/robinhood.py`): builds + Ed25519-signs official
 Robinhood Crypto requests via an **injectable signer** (no hard crypto dep;
 `default_ed25519_signer` uses `cryptography`/`PyNaCl` if installed). Request/
 header construction is unit-tested offline; `place_order` refuses unless
 `TRADING_LIVE=1` and a `transport` is supplied. Engine order routing to live is
 intentionally not wired — the bot stays on `PaperBroker`.
- `gary/trading/montecarlo.py` bootstraps out-of-sample trades into an outcome
 distribution (P(reach goal), risk of ruin, p5/p50/p95).
- Dev gotcha: `uvicorn --reload` only watches `.py` files, NOT the Jinja
 template (`gary/templates/dashboard.html`, read once at import) or `static/`
 assets. After editing the template, **restart** the server to pick it up; bump
 the `?v=` query on the `dashboard.js` include when changing the JS so browsers
 don't serve a stale cached script against a new template.
- `POST /api/trading/optimize` (`gary/trading/optimize.py`) is **rolling
 walk-forward**:
 it slides K (train, test) folds through history with a **purge/embargo** gap
 between train and test, tunes on each train window (robust selection above),
 scores only on the following out-of-sample window, then aggregates OOS across
 folds plus a buy-and-hold benchmark, an overfit gap, a deflated Sharpe, and a
 Monte Carlo of the OOS trades. It fetches each symbol's series once and reuses
 it across all candidates and folds. Deterministic offline. Expect OOS well
 below in-sample; in a bull run it usually loses to buy-and-hold, and in a
 downturn the defensive/low-turnover picks tend to beat it by losing less —
 surfacing that honestly is the point.
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
