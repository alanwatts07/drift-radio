# drift-radio

An AI radio station that generates live content between songs — song facts, news breaks, and agent commentary — using Claude CLI, OpenAI TTS, and Liquidsoap.

## What it does

Music plays. When a track changes, Claude writes a 40-second script about the artist. OpenAI converts it to speech (onyx voice, broadcast loudness). Liquidsoap queues it to play at the end of the current song — no hard cuts, no silence. At :30 past the hour, Claude searches the web for real news and reads it on air. At the top of the hour, the drift agents (Max, Beth, Gerald) each give their take on a topic.

No manual intervention. No pre-recorded content. Every segment is generated live.

## Architecture

```
Spotify (BUTT) ──────────────────────────────┐
Local music (fallback playlist) ──────────── Liquidsoap → Icecast → stream
AI segments (Python queue) ──────────────────┘
         ↑
Python scheduler
├── spotify_watcher.py   track change detection (spotipy)
├── segment_generator.py Claude CLI + drift agents API
├── tts_renderer.py      OpenAI TTS (onyx, loudnorm to -14 LUFS)
├── audio_mixer.py       speech over music bed (optional)
└── liquidsoap_queue.py  telnet push to Liquidsoap request queue
```

**Priority chain:** injected AI segments > Spotify passthrough > local playlist

**Smart timing:** segment generation starts immediately on track change. The scheduler polls remaining playback time and queues the segment only when ≤15 seconds are left — so it plays at the natural track boundary, never mid-song.

## Stack

- **Liquidsoap** — radio engine (fallback chain, request queue, Icecast output)
- **Icecast** — public stream output (MP3 192kbps)
- **Claude CLI** — content generation (web search for news, song facts, commentary)
- **OpenAI TTS** — `onyx` voice, normalized to broadcast loudness via ffmpeg
- **spotipy** — Spotify API for track change detection
- **Docker Compose** — Icecast + Liquidsoap containers

## Setup

```bash
git clone https://github.com/alanwatts07/drift-radio
cd drift-radio
cp .env.example .env
# fill in OPENAI_API_KEY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

docker compose up -d
python scheduler.py
```

Stream at `http://localhost:8000/live.mp3`

## Segment types

| Trigger | Content | Length |
|---------|---------|--------|
| Track change | 3 facts about artist/track (Claude) | ~40s |
| :30 past hour | 3 real news stories with web search (Claude) | ~60s |
| :00 hour | News + agent takes from Max, Beth, Gerald | ~3-4 min |
| Random (20-40 min) | Drift agent commentary on a topic | ~45s |

## Content generation

```bash
# Claude CLI — dry deadpan host voice
claude -p "You are a dry, deadpan radio host..." --max-turns 3

# Drift agents API
POST https://agents-api.mattcorwin.dev/chat
{"agent": "max", "message": "Give me your take on [topic] as a 45-second radio segment"}
```

## Spotify passthrough (BUTT)

Connect BUTT to `localhost:8005`, mount `/spotify`, password `hackme`. Liquidsoap switches from local files to the live stream automatically and falls back when disconnected.

## Cost

OpenAI TTS: ~$0.015/1000 chars. A 1-minute segment ≈ $0.014. Negligible.
Claude content generation: free (Max subscription, Claude CLI).
