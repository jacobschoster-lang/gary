# gary

Automated finance-content platform: a set of agents plus a dashboard that
produce and track daily YouTube finance videos and shorts.

The agents pull **real, live data** from free public APIs (no keys needed) and
fall back to deterministic sample data when offline, so the app always runs and
stays testable. Videos are animated stick-figure stories with a synthesized
voiceover. Remaining integrations (LLM scripting, YouTube Data API upload) plug
into clearly marked seams.

Live data sources (all free, no API key, with graceful fallback):
- Stocks (#2): Yahoo Finance chart API — `gary/data/stocks.py`
- Crypto (#3): CoinGecko markets API — `gary/data/crypto.py`
- News (#1): Google News RSS grounds transcripts in current headlines — `gary/data/news.py`

Voiceover uses gTTS (`gary/render/tts.py`); it needs internet and degrades to a
silent video if unavailable. Captions are timed per sentence (subtitle-style),
synced to the narration.

### LLM scripting (optional)

`gary/agents/llm.py` upgrades transcript copy using any OpenAI-compatible
chat-completions API. It activates only when `OPENAI_API_KEY` is set and falls
back to the built-in deterministic script otherwise. Configure:

- `OPENAI_API_KEY` (required to enable)
- `OPENAI_BASE_URL` (default `https://api.openai.com/v1`)
- `OPENAI_MODEL` (default `gpt-4o-mini`)

The LLM must return the four headings the renderer styles (`Hook`, `The Data`,
`Analysis`, `Call To Action`); otherwise the deterministic script is used.

No-key local option (dev): run a local model with [Ollama] and point the app at
it — no account or API key required:

```bash
ollama serve &
ollama pull llama3.2:3b
export OPENAI_API_KEY=ollama         # any dummy value; Ollama ignores it
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_MODEL=llama3.2:3b
```

This is great for local/sandbox use; the scheduled GitHub Actions job still needs
a hosted provider key (a local model isn't available in CI).

[Ollama]: https://ollama.com

## Roadmap (tracked in issues) → starter modules

Each issue now has a runnable starter module with a clear extension seam
(marked `# NOTE: replace ...`) so work can begin independently.

| Issue | Focus | Starter module / seam |
|-------|-------|-----------------------|
| #1 | YouTube finance transcripts | `gary/agents/transcript_agent.py` → `_draft_body` |
| #2 | Stock market + YouTube trends | `gary/agents/trends_agent.py` → `_fetch` / `_fetch_youtube` |
| #3 | Crypto / DeFi trends | `gary/agents/trends_agent.py` → `_fetch("crypto")` |
| #4 | Daily long videos + shorts | `gary/agents/video_agent.py` → `_broll_for` |
| #5 | Thumbnails | `gary/agents/thumbnail_agent.py` → `render_svg` |
| #6 | Upload + comments + performance | `gary/agents/publisher_agent.py` → `upload` / `track` |
| #7 | Tracking dashboard | `gary/app.py` + `gary/templates/dashboard.html` |

`gary/pipeline.py` chains all of them into one `run_daily()` flow:
trend → transcript → long+short video plans → thumbnail → publish → track.

## Personal finance (dashboard)

The dashboard includes a "My finances" tool (`gary/finance/`) where you enter or
import your accounts and it:

- tracks cashflow/income from imported transactions — upload a bank **CSV**
  export (signed `Amount` or `Debit`/`Credit` columns) or a statement
  **image snapshot** (best-effort OCR via Tesseract); transactions are
  auto-categorized into income sources and expense categories,
- tracks net worth (assets − debts) with a saved history of snapshots,
- builds debt-payoff plans and compares avalanche (highest APR first) vs snowball
  (smallest balance first), showing payoff time and total interest,
- computes a financial-health score with prioritized recommendations.

Data is entered by the user and persisted locally to `finance_data/profile.json`
(configurable via `GARY_FINANCE_FILE`).

Automatic bank aggregation via **Plaid** (`gary/finance/plaid.py`) pulls real
balances (→ assets/debts) and transactions (→ cashflow). Click "Connect a bank
(Plaid)" on the dashboard, log in through Plaid Link, and accounts sync in. It's
enabled only when configured, and degrades to manual/file import otherwise:

- `PLAID_CLIENT_ID`, `PLAID_SECRET` (required to enable)
- `PLAID_ENV` — `sandbox` (default) | `development` | `production`

In `sandbox`, log in with Plaid's test credentials (`user_good` / `pass_good`).
The access token is stored locally in `finance_data/plaid.json` (gitignored). Endpoints: `GET/POST /api/finance`, `POST /api/finance/sample`,
`POST /api/finance/import` (multipart file upload: CSV or image), and Plaid:
`GET /api/finance/plaid/status`, `POST /api/finance/plaid/link-token`,
`POST /api/finance/plaid/exchange`, `POST /api/finance/plaid/sync`. Image OCR
requires the `tesseract` system binary (pre-installed on the dev VM).

## Real estate search

The dashboard "Land & homes for sale" card and `GET /api/realestate` find active
listings by radius, minimum acreage, and max price (e.g. within 25 mi of
Cincinnati, OH, 5+ acres, under $350k). Live data comes from **RentCast**
(`gary/realestate/`) when `RENTCAST_API_KEY` is set (free tier available);
otherwise it returns a small labeled **sample** dataset so the feature works
offline. Results are filtered client-side by acreage/price and annotated with
distance from the search center.

Params: `city`, `state`, `radius` (mi), `min_acres`, `max_price`.

## Development

Requires Python 3.10+.

### Run on your Mac (dashboard at http://localhost:8000)

One-time setup (clone the repo, then from the repo root):

```bash
brew install python@3.12   # if you don't have Python 3 yet
bash scripts/install.sh
```

**Interactive dev server** (opens the dashboard in your browser):

```bash
bash scripts/mac-dashboard.sh
```

**Always-on background service** (starts at login, survives restarts):

```bash
bash scripts/install-mac-service.sh
```

Optional system tools for full features: `brew install ffmpeg tesseract` (video
rendering + statement OCR).

### Live dashboard (public URL)

Deploy to **[Render](https://render.com)** for a permanent URL you can open from
any device (Mac, phone, etc.) — no VM or tunnel required.

1. Push this repo to GitHub (already at `github.com/jacobschoster-lang/gary`)
2. Go to [Render Dashboard → New → Blueprint](https://dashboard.render.com/blueprints)
3. Connect the `gary` repo — Render reads `render.yaml` automatically
4. Click **Apply** — you'll get a URL like `https://gary-dashboard.onrender.com`

Or use the one-click deploy button after merging (add to README):

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/jacobschoster-lang/gary)

Optional env vars in the Render dashboard (Settings → Environment):
`OPENAI_API_KEY`, `YOUTUBE_API_KEY`, `PLAID_CLIENT_ID`/`PLAID_SECRET`,
`RENTCAST_API_KEY`, YouTube OAuth vars for uploads.

**Docker (any host):**

```bash
docker build -t gary .
docker run -p 8000:8000 -v gary-data:/data gary
# open http://localhost:8000
```

Production entrypoint: `bash scripts/start-prod.sh` (reads `$PORT`, defaults to 8000).

### Linux / cloud VM

```bash
# 1. Create the virtualenv and install dependencies
bash scripts/install.sh
# or manually:
# python3 -m venv .venv
# .venv/bin/pip install --upgrade pip
# .venv/bin/pip install -r requirements.txt

# 2. Run the dev server (auto-reload)
.venv/bin/uvicorn gary.app:app --reload --host 0.0.0.0 --port 8000
# open http://localhost:8000

# 3. Lint
.venv/bin/ruff check .

# 4. Test
.venv/bin/pytest -q
```

## Daily posting to YouTube (@StickfigureFinance-r8m, 08:00 ET)

Posting runs on GitHub Actions (`.github/workflows/daily-post.yml`), not the
cloud VM. Cron is UTC-only, so it triggers at 12:00 and 13:00 UTC and the guard
in `gary/jobs/schedule.py` only runs the job at the real 08:00 America/New_York
(handles EDT/EST). The job (`gary/jobs/daily_post.py`) runs the pipeline, builds
title/description/tags, and uploads via `gary/integrations/youtube.py`.

Required GitHub repo **secrets** (Settings → Secrets and variables → Actions):
- `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` — OAuth client (Desktop app)
- `YOUTUBE_REFRESH_TOKEN` — minted once with `scripts/youtube_authorize.py`
  using the Google account that owns the channel
- `YOUTUBE_API_KEY` — optional; enables live YouTube trends + real view counts
  in the dashboard (free Google Cloud API key)
- `OPENAI_API_KEY` — optional; upgrades transcript copy and comment replies

Optional repo **variables**:
- `YOUTUBE_PRIVACY` — `private` (default) | `unlisted` | `public`
- `GARY_VIDEO_FILE` — path to the rendered MP4 to upload

Mint a refresh token locally (needs a browser):

```bash
export YOUTUBE_CLIENT_ID=...
export YOUTUBE_CLIENT_SECRET=...
.venv/bin/python scripts/youtube_authorize.py
```

Without credentials the job does a safe **dry run** (renders the video + writes a
manifest to `out/`, uploads nothing).

### Animated stick-figure videos

`gary/render/` turns a content plan into an animated **stick-figure** MP4: a
title card, then one scene per story beat with a gesturing stick figure, a
finance prop (coin / bar chart / up-arrow), and a narration caption. The daily
job auto-renders this video when `GARY_VIDEO_FILE` is not set. Rendering uses
Pillow for frames and the system **`ffmpeg`** binary for H.264 encoding (the
workflow installs ffmpeg; it's also pre-installed on the dev VM). Preview one:

```bash
.venv/bin/python -c "from gary.pipeline import ContentPipeline; from gary.render import render_story; render_story(ContentPipeline().run_daily(topic='Bitcoin ETF inflows'), 'story.mp4')"
```

Or in the dashboard, click **Preview stick-figure video** (`GET /api/story.mp4?topic=...`).
Voiceover is available via `?voice=true` (gTTS; needs network). The daily job
renders long + short MP4s and a PNG thumbnail automatically.

Run/inspect manually:

```bash
.venv/bin/python -m gary.jobs.daily_post --topic "Bitcoin ETF inflows" --force
.venv/bin/python -m gary.jobs.schedule --check   # exit 0 iff it's 08:00 ET now
```

## API

- `GET /` — dashboard
- `GET /api/health` — health check
- `GET /api/trends?market=stocks|crypto|quantum&limit=N` — trending assets
- `GET /api/youtube-trends?limit=N` — trending YouTube finance topics
- `POST /api/transcript` — body `{"topic": "...", "data_points": [...]}` → transcript
- `GET /api/transcripts` — recently generated transcripts
- `GET /api/thumbnail.svg?topic=...` — rendered thumbnail (SVG)
- `POST /api/pipeline/run` — body `{"topic": "..."?}` → full daily content plan
- `GET /api/videos` — published videos + performance metrics
