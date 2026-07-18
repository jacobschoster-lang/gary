# gary

Automated finance-content platform: a set of agents plus a dashboard that
produce and track daily YouTube finance videos and shorts.

This repo is an early starter scaffold. The agents currently use deterministic,
offline logic so the app runs and is testable without any API keys. Real
integrations (LLMs, market-data APIs, YouTube Data API, thumbnail generation,
uploads) plug into the clearly marked seams in `gary/agents/`.

## Roadmap (tracked in issues)

1. Agent to build YouTube finance transcripts from real internet data (#1)
2. Agent to scrape the stock market and YouTube for trending topics (#2)
3. Agent to scrape crypto for trending coins / DeFi opportunities (#3)
4. Agent to produce daily 10-min videos and daily shorts (#4)
5. Agent to auto-generate thumbnails (#5)
6. Agent to upload videos, manage comments, track performance (#6)
7. Dashboard to track everything (#7)

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

## API

- `GET /` — dashboard
- `GET /api/health` — health check
- `GET /api/trends?market=stocks|crypto&limit=N` — trending assets
- `POST /api/transcript` — body `{"topic": "...", "data_points": [...]}` → transcript
- `GET /api/transcripts` — recently generated transcripts
