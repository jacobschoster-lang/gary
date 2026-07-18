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

## Development

Requires Python 3.10+.

```bash
# 1. Create the virtualenv and install dependencies
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

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
Currently the video has no voiceover; TTS narration is the next enhancement.

Run/inspect manually:

```bash
.venv/bin/python -m gary.jobs.daily_post --topic "Bitcoin ETF inflows" --force
.venv/bin/python -m gary.jobs.schedule --check   # exit 0 iff it's 08:00 ET now
```

## API

- `GET /` — dashboard
- `GET /api/health` — health check
- `GET /api/trends?market=stocks|crypto&limit=N` — trending assets
- `GET /api/youtube-trends?limit=N` — trending YouTube finance topics
- `POST /api/transcript` — body `{"topic": "...", "data_points": [...]}` → transcript
- `GET /api/transcripts` — recently generated transcripts
- `GET /api/thumbnail.svg?topic=...` — rendered thumbnail (SVG)
- `POST /api/pipeline/run` — body `{"topic": "..."?}` → full daily content plan
- `GET /api/videos` — published videos + performance metrics
