# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FTR (Fun Time Radio) is a full-stack AI-powered radio station combining Spotify streaming, listener song requests, and AI-generated content segments. It streams at radio.ftrai.uk via Cloudflare Tunnel.

## Architecture

Three independent apps in one repo:

- **`/ui/`** — Next.js 16 + React 19 + Tailwind 4 frontend. Main player page (`app/page.tsx`) and admin panel (`app/bartender/page.tsx`).
- **`/api/`** — FastAPI backend (`api.py`). Handles Spotify OAuth, search, queue, announcements, mode switching. Runs on port 8080.
- **`/engine/`** — Python scheduler + Liquidsoap/Icecast streaming. `scheduler.py` orchestrates AI segment generation on a timed schedule, `segment_generator.py` calls Claude CLI for content and OpenAI TTS for voice rendering.

### Audio Pipeline

Spotify audio is piped via ffmpeg (Windows host) into Liquidsoap's harbor input on port 8005. Liquidsoap mixes four priority layers: urgent announcements > scheduled segments > Spotify passthrough > local music fallback. Output goes to Icecast on port 8000 at `/live.mp3`.

### Key Integration Points

- All Spotify API calls route through the FastAPI backend for shared rate limiting (3 calls/30s with 429 backoff).
- AI segments use **Claude CLI** (the `claude` command) for content generation, not the API directly.
- TTS uses OpenAI API (shimmer voice, normalized to -14 LUFS).
- The engine communicates with Liquidsoap via telnet on port 1234.

## Commands

### Frontend (`/ui/`)
```bash
cd ui && npm install        # Install dependencies
npm run dev                 # Dev server on :3000
npm run build               # Production build
npm run lint                # ESLint
```

### API (`/api/`)
```bash
cd api && pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8080
```

### Engine (`/engine/`)
```bash
cd engine && docker compose up -d    # Start Icecast + Liquidsoap
cd engine && pip install -r requirements.txt
python scheduler.py                   # Run segment scheduler (long-running)
```

### Full Stack
```bash
./start_radio.sh    # Starts everything: venv setup, Docker, API, UI, cloudflared
```

## Environment Variables

Defined in `.env` files at root, `/api/`, and `/engine/`. See `.env.example` for the template. Key variables: `OPENAI_API_KEY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REFRESH_TOKEN`, `ICECAST_PASSWORD`, `DRIFT_AGENTS_API_URL`, `BARTENDER_PASSWORD`.

## Important Patterns

- **All FastAPI endpoints must be `def`, not `async def`** — async caused deadlocks with the Spotify token caching. This was an intentional fix.
- **Segment types and schedule**: song facts at :20/:40, news at :50, full broadcasts at :00, random riffs every 20-40 min. Configured in `engine/config.py`.
- **The frontend polls `/api/nowplaying`, `/api/queue`, and `/api/status`** every 30 seconds for live updates.
- **No test framework** is configured. Testing is manual via API endpoints.
