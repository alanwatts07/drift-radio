# FTR — Fun Time Radio

[![Live](https://img.shields.io/badge/stream-LIVE-brightgreen?style=flat-square)](https://radio.ftrai.uk)
[![Next.js](https://img.shields.io/badge/Next.js-15-black?style=flat-square&logo=next.js)](https://nextjs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![Spotify](https://img.shields.io/badge/Spotify-Integration-1DB954?style=flat-square&logo=spotify)](https://developer.spotify.com)
[![Icecast](https://img.shields.io/badge/Icecast-MP3%20192kbps-blue?style=flat-square)](https://icecast.org)
[![Claude](https://img.shields.io/badge/Claude-AI%20Segments-cc785c?style=flat-square)](https://claude.ai)
[![n8n](https://img.shields.io/badge/n8n-News%20Roundtable-ff6d5a?style=flat-square&logo=n8n)](https://n8n.io)
[![License](https://img.shields.io/badge/license-MIT-yellow?style=flat-square)](LICENSE)

**Live at [radio.ftrai.uk](https://radio.ftrai.uk)**

An AI-powered radio station with live song requests, queue tracking, AI-generated segments between songs, and multi-voice news roundtables via n8n + drift agents.

![FTR Screenshot](screenshot.png)

## What it does

Music plays through Spotify. Listeners search and queue songs from their phone — their name shows next to their request. Between tracks, Claude writes scripts about the artist, reads real news, or riffs with the drift agents. OpenAI TTS converts it to speech. Liquidsoap handles priority mixing and streams to Icecast.

No manual intervention. No pre-recorded content. Every segment is generated live.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  UI (Next.js)          radio.ftrai.uk               │
│  Search, queue songs, see now playing, listen live   │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  API (FastAPI)        ftr-api.ftrai.uk              │
│  Spotify OAuth, search, queue, now playing, stats    │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  Engine (Liquidsoap + Icecast)                       │
│  Priority: AI segments > Spotify > local playlist    │
│                                                      │
│  Spotify → VoiceMeeter B1 → ffmpeg → harbor:8005    │
│  AI segments → TTS → request queue                   │
│  Everything → Icecast /live.mp3                      │
└─────────────────────────────────────────────────────┘
```

## Project Structure

```
ftr-radio/
├── ui/              Next.js frontend (song search, queue, player)
├── api/             FastAPI backend (Spotify API, rate limit tracking)
├── engine/          Liquidsoap config, Icecast, AI segment generation
│   ├── liquidsoap/  Radio engine config
│   ├── scheduler.py AI segment scheduling
│   ├── tts_renderer.py  OpenAI TTS (onyx voice, -14 LUFS)
│   └── docker-compose.yml
└── README.md
```

## Features

- **Live streaming** via Icecast at `radio.ftrai.uk`
- **Song requests** — search Spotify, tap to queue, enter your name
- **Queue display** — purple dot + requester name next to queued songs
- **Now playing** — spinning vinyl with album art, progress bar
- **AI segments** — Claude-generated artist facts, news, agent commentary
- **Rate limit monitoring** — `/spotify/stats` tracks API burn rate and 429s
- **Spotify passthrough** — VoiceMeeter B1 → ffmpeg → Liquidsoap harbor

## Stack

- **Next.js** — frontend (search, queue, player)
- **FastAPI** — API layer (Spotify OAuth, caching, rate limit tracking)
- **Liquidsoap** — radio engine (fallback chain, request queue)
- **Icecast** — stream output (MP3 192kbps)
- **Claude CLI** — AI content generation
- **OpenAI TTS** — `onyx` voice, broadcast loudness
- **Cloudflare Tunnel** — public access without port forwarding

## Setup

```bash
git clone https://github.com/alanwatts07/drift-radio
cd drift-radio

# API
cd api && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in Spotify credentials
uvicorn api:app --host 0.0.0.0 --port 8080

# UI
cd ../ui && npm install && npm run dev

# Engine
cd ../engine && docker compose up -d
python scheduler.py
```

## Spotify Audio Routing (Windows)

```powershell
ffmpeg -f dshow -i audio="Voicemeeter Out B1 (VB-Audio Voicemeeter VAIO)" -ac 2 -ar 44100 -acodec libmp3lame -b:a 192k -f mp3 icecast://source:hackme@localhost:8005/spotify
```

## Segment Types

| Trigger | Content | Length |
|---------|---------|--------|
| Track change | 3 facts about artist/track (Claude) | ~40s |
| :30 past hour | 3 real news stories with web search | ~60s |
| :00 hour | News + agent takes from Max, Beth, Gerald | ~3-4 min |
| :50 past hour | **n8n News Roundtable** — multi-voice broadcast (see below) | ~3 min |
| Random (20-40 min) | Drift agent commentary on a topic | ~45s |

## n8n News Roundtable

An automated multi-voice news broadcast powered by an n8n workflow (`radio_roundtable.json`).

**Flow:** Scheduler (or n8n cron) triggers webhook → n8n fetches 4 Google News RSS feeds (general, tech, ethics, psychology) → categorizes stories → POSTs to `/broadcast/news` → each drift agent gives their take with their own OpenAI TTS voice and mood-based speaking speed → Terence wraps up and sends it back to the music → stitched into one MP3 → pushed to liquidsoap.

| Agent | Domain | Voice |
|-------|--------|-------|
| Max | Tech news | echo |
| Beth | Ethics / moral compass | nova |
| Private Aye | Psychology / profiling | fable |
| Terence | Anchor / wrap-up | onyx |

Import `radio_roundtable.json` into n8n to use. Requires the API running on port 8080.

## Use Cases

- **Bar jukebox** — Put a QR code on the counter. Customers scan, search, and queue songs from their phones. Their name shows up on screen next to their pick. No more fighting over the aux cord.
- **Custom business radio** — Restaurants, coffee shops, retail stores. Branded AI DJ that talks about your specials, reads promotions, and takes song requests from customers.
- **House parties** — Share the link. Everyone queues songs. The AI host keeps things moving between tracks with commentary and crowd shoutouts.
- **Remote hangouts** — Friends across different cities listen to the same stream. Everyone queues songs. Shared music experience without being in the same room.
- **Twitch/Discord communities** — Community radio that your audience controls. AI segments react to what's playing and who's requesting.

## Cost

OpenAI TTS: ~$0.015/1000 chars (~$0.014 per 1-minute segment). Negligible.
Claude content generation: free (Max subscription, Claude CLI).
