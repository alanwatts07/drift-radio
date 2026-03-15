#!/usr/bin/env python3
"""
FTR — Fun Time Radio
FastAPI backend
"""

import os
import sys
import subprocess
import logging
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# Add drift-radio engine to path so we can reuse tts_renderer + liquidsoap_queue
DRIFT_RADIO_DIR = os.getenv("DRIFT_RADIO_DIR", "/home/morpheus/Hackstuff/drift-radio")
ENGINE_DIR = os.path.join(DRIFT_RADIO_DIR, "engine")
sys.path.insert(0, ENGINE_DIR)
sys.path.insert(0, DRIFT_RADIO_DIR)  # fallback for old layout
import tts_renderer
import liquidsoap_queue

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="FTR API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BARTENDER_PASSWORD = os.getenv("BARTENDER_PASSWORD", "ftr2024")
SEGMENTS_DIR = Path(DRIFT_RADIO_DIR) / "segments"
SPOTIFY_API = "https://api.spotify.com/v1"


# --- Auth ---

def require_bartender(x_password: Optional[str] = Header(None)):
    if x_password != BARTENDER_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")


# --- Spotify ---

_spotify_token = {"access_token": None, "expires_at": 0}
_rate_limit_backoff_until = 0  # global backoff timestamp

def _refresh_spotify_token() -> str:
    """Refresh the Spotify token via API using env var refresh token."""
    import time
    if _spotify_token["expires_at"] > time.time() + 60 and _spotify_token["access_token"]:
        return _spotify_token["access_token"]
    resp = requests.post("https://accounts.spotify.com/api/token", data={
        "grant_type": "refresh_token",
        "refresh_token": os.getenv("SPOTIFY_REFRESH_TOKEN"),
        "client_id": os.getenv("SPOTIFY_CLIENT_ID"),
        "client_secret": os.getenv("SPOTIFY_CLIENT_SECRET"),
    })
    resp.raise_for_status()
    data = resp.json()
    _spotify_token["access_token"] = data["access_token"]
    _spotify_token["expires_at"] = int(time.time()) + data.get("expires_in", 3600)
    log.info("[spotify] token refreshed successfully")
    return _spotify_token["access_token"]

import time as _time
import threading
from collections import deque

_spotify_cache_data = {}  # in-memory cache for nowplaying
_spotify_cache_ts = 0

# --- Spotify call throttle ---
# Ensures minimum gap between ANY Spotify API calls, even from concurrent users
MAX_CALLS_PER_WINDOW = 3
WINDOW_SECONDS = 30.0
_call_timestamps = deque()  # timestamps of recent Spotify calls
_throttle_lock = threading.Lock()

def _throttle(block: bool = True) -> bool:
    """Enforce max 3 Spotify API calls per 30 second window.
    If block=True, waits. If block=False, returns False immediately when limited."""
    with _throttle_lock:
        now = _time.time()
        # Prune calls outside the window
        while _call_timestamps and _call_timestamps[0] < now - WINDOW_SECONDS:
            _call_timestamps.popleft()
        # If at limit, either wait or bail
        if len(_call_timestamps) >= MAX_CALLS_PER_WINDOW:
            wait = _call_timestamps[0] + WINDOW_SECONDS - now + 0.1
            if not block:
                log.debug(f"[throttle] 3/{WINDOW_SECONDS:.0f}s limit, skipping (non-blocking)")
                return False
            log.info(f"[throttle] 3/{WINDOW_SECONDS:.0f}s limit hit, waiting {wait:.1f}s")
            _time.sleep(wait)
        _call_timestamps.append(_time.time())
        return True

# --- Rate limit tracking ---
_api_calls = deque()  # timestamps of all Spotify API calls
_rate_limit_log = []  # list of {timestamp, endpoint, retry_after}

def _track_call(endpoint: str):
    """Record an API call for rate monitoring."""
    now = _time.time()
    _api_calls.append((now, endpoint))
    # Prune calls older than 1 hour
    cutoff = now - 3600
    while _api_calls and _api_calls[0][0] < cutoff:
        _api_calls.popleft()

def _track_429(endpoint: str, retry_after: int):
    """Log a 429 rate limit event."""
    event = {
        "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": _time.time(),
        "endpoint": endpoint,
        "retry_after": retry_after,
        "calls_last_hour": len(_api_calls),
    }
    _rate_limit_log.append(event)
    log.error(f"[spotify] 429 RATE LIMITED on {endpoint} — retry after {retry_after}s — "
              f"{len(_api_calls)} calls in last hour")

def _check_backoff() -> bool:
    """Return True if we're in backoff and should NOT make a call."""
    global _rate_limit_backoff_until
    if _time.time() < _rate_limit_backoff_until:
        remaining = int(_rate_limit_backoff_until - _time.time())
        log.warning(f"[spotify] backoff active — {remaining}s remaining, using cache")
        return True
    return False

def _handle_429_response(resp, endpoint: str):
    """Set global backoff on 429. Cap at 5 min — Spotify dev mode sends insane values."""
    global _rate_limit_backoff_until
    raw_retry = int(resp.headers.get("Retry-After", 30))
    retry_after = min(raw_retry, 300)  # cap at 5 minutes, not 4 hours
    _rate_limit_backoff_until = _time.time() + retry_after
    _track_429(endpoint, raw_retry)

def spotify_get(path: str, params: dict = None, block: bool = True) -> dict:
    if _check_backoff():
        return None
    if not _throttle(block=block):
        return None
    _track_call(path)
    token = _refresh_spotify_token()
    resp = requests.get(f"{SPOTIFY_API}{path}", headers={"Authorization": f"Bearer {token}"}, params=params, timeout=10)
    if resp.status_code == 204:
        return {}
    if resp.status_code == 429:
        _handle_429_response(resp, path)
        return None
    resp.raise_for_status()
    return resp.json()

def spotify_post(path: str, json_data: dict = None) -> dict:
    if _check_backoff():
        return None
    _throttle()
    _track_call(path)
    token = _refresh_spotify_token()
    resp = requests.post(f"{SPOTIFY_API}{path}", headers={"Authorization": f"Bearer {token}"}, json=json_data, timeout=10)
    if resp.status_code in (200, 204) and (not resp.text or not resp.text.strip()):
        return {}
    if resp.status_code == 204:
        return {}
    if resp.status_code == 429:
        _handle_429_response(resp, path)
        return None
    resp.raise_for_status()
    return resp.json()

def spotify_put(path: str, json_data: dict = None) -> dict:
    if _check_backoff():
        return None
    _throttle()
    _track_call(path)
    token = _refresh_spotify_token()
    resp = requests.put(f"{SPOTIFY_API}{path}", headers={"Authorization": f"Bearer {token}"}, json=json_data, timeout=10)
    if resp.status_code in (200, 204) and (not resp.text or not resp.text.strip()):
        return {}
    if resp.status_code == 204:
        return {}
    if resp.status_code == 429:
        _handle_429_response(resp, path)
        return None
    resp.raise_for_status()
    return resp.json()


# --- Models ---

class RawAnnouncement(BaseModel):
    text: str
    now: bool = False  # True = interrupt current song, False = queue after

class AIAnnouncement(BaseModel):
    prompt: str
    now: bool = False

class NewsRoundtableRequest(BaseModel):
    headlines: list[str]        # 2-3 general news headlines
    tech_story: str             # tech story for Max
    ethics_story: str           # ethics story for Beth
    psych_story: str            # psychology/profiling story for Earl Von Schnuff
    now: bool = False           # True = interrupt, False = queue after current song


class QueueRequest(BaseModel):
    uri: str


# --- Announce endpoints ---

def _render_and_push(text: str, out: Path, priority: bool):
    """TTS render and push to Liquidsoap in a background thread."""
    import traceback
    try:
        log.info(f"[announce] rendering TTS to {out}")
        # Skip ffmpeg stereo/loudnorm — push TTS output directly
        from openai import OpenAI as _OAI
        _client = _OAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = _client.audio.speech.create(
            model="tts-1",
            voice="shimmer",
            input=text,
            speed=0.95,
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        response.stream_to_file(str(out))
        log.info(f"[announce] TTS done, size: {out.stat().st_size}")
        result = liquidsoap_queue.push_segment(out, priority=priority)
        log.info(f"[announce] push result: {result}")
    except Exception as e:
        log.error(f"[announce] failed: {e}\n{traceback.format_exc()}")


@app.post("/announce/raw")
def announce_raw(body: RawAnnouncement, _=Depends(require_bartender)):
    """Play text verbatim on air."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    log.info(f"[announce/raw] {'NOW ' if body.now else ''}{body.text[:60]}")
    out = SEGMENTS_DIR / "announce_raw.mp3"

    t = threading.Thread(target=_render_and_push, args=(body.text, out, body.now))
    t.start()

    return {"status": "rendering", "text": body.text}


def _render_ai_and_push(prompt: str, out: Path, priority: bool):
    """Generate script with Claude, TTS render, push to Liquidsoap."""
    import traceback
    try:
        system = (
            "You are a dry, deadpan radio host for a bar called FTR (Fun Time Radio). "
            "Write a short, punchy on-air announcement (max 20 seconds when read aloud). "
            "No filler, no fake enthusiasm. Just say the thing. Output only the script."
        )
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        result = subprocess.run(
            [
                "claude", "-p", f"Announcement topic: {prompt}",
                "--system-prompt", system,
                "--max-turns", "1",
            ],
            capture_output=True, text=True, timeout=60,
            env=env,
        )
        if result.returncode != 0:
            log.error(f"[announce/ai] Claude failed: {result.stderr[:200]}")
            return
        script = result.stdout.strip()
        log.info(f"[announce/ai] script: {script[:80]}")
        # Direct TTS — skip ffmpeg stereo/loudnorm
        from openai import OpenAI as _OAI
        _client = _OAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = _client.audio.speech.create(
            model="tts-1",
            voice="shimmer",
            input=script,
            speed=0.95,
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        response.stream_to_file(str(out))
        liquidsoap_queue.push_segment(out, priority=priority)
        log.info(f"[announce/ai] delivered: {script[:60]}")
    except Exception as e:
        log.error(f"[announce/ai] failed: {e}\n{traceback.format_exc()}")


@app.post("/announce/ai")
def announce_ai(body: AIAnnouncement, _=Depends(require_bartender)):
    """Claude generates a script from prompt, plays it on air."""
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    log.info(f"[announce/ai] prompt: {body.prompt[:60]}")
    out = SEGMENTS_DIR / "announce_ai.mp3"

    t = threading.Thread(target=_render_ai_and_push, args=(body.prompt, out, body.now))
    t.start()

    return {"status": "generating — Claude + TTS in background", "prompt": body.prompt}


# --- News roundtable (n8n webhook target) ---

def _generate_roundtable(headlines, tech_story, ethics_story, psych_story, priority):
    """Generate multi-voice news roundtable and push to liquidsoap."""
    import traceback
    try:
        import segment_generator
        path = segment_generator.news_roundtable(headlines, tech_story, ethics_story, psych_story)
        if path and Path(path).exists():
            liquidsoap_queue.push_segment(path, priority=True)
            log.info(f"[roundtable] broadcast delivered: {path}")
    except Exception as e:
        log.error(f"[roundtable] failed: {e}\n{traceback.format_exc()}")


@app.post("/broadcast/news")
def broadcast_news(body: NewsRoundtableRequest, _=Depends(require_bartender)):
    """n8n calls this with categorized news stories. Generates a multi-voice
    roundtable broadcast with each drift agent using their own TTS voice."""
    if not body.headlines and not body.tech_story and not body.ethics_story and not body.psych_story:
        raise HTTPException(status_code=400, detail="At least one story required")

    log.info(f"[roundtable] received: {len(body.headlines)} headlines, "
             f"tech={bool(body.tech_story)}, ethics={bool(body.ethics_story)}, psych={bool(body.psych_story)}")

    t = threading.Thread(
        target=_generate_roundtable,
        args=(body.headlines, body.tech_story, body.ethics_story, body.psych_story, body.now),
    )
    t.start()

    return {"status": "generating roundtable broadcast in background",
            "segments": ["anchor"] + [a for a, s in [("max", body.tech_story), ("beth", body.ethics_story), ("private_aye", body.psych_story)] if s]}


# --- Spotify endpoints ---

@app.get("/nowplaying")
def now_playing():
    """Current track info + album art. Cached for 5s to avoid rate limits."""
    global _spotify_cache_data, _spotify_cache_ts
    try:
        now = _time.time()
        if now - _spotify_cache_ts < 30 and _spotify_cache_data:
            return _spotify_cache_data
        pb = spotify_get("/me/player", block=False)
        if pb is None:  # rate limited or throttled — return cache
            if _spotify_cache_data:
                return _spotify_cache_data
            return {"playing": False}
        if not pb or not pb.get("item"):
            _spotify_cache_data = {"playing": False}
            _spotify_cache_ts = now
            return _spotify_cache_data
        item = pb["item"]
        images = item.get("album", {}).get("images", [])
        album_art = images[0]["url"] if images else None
        _spotify_cache_data = {
            "playing": pb.get("is_playing", False),
            "artist": item["artists"][0]["name"] if item.get("artists") else "Unknown",
            "track": item["name"],
            "album": item.get("album", {}).get("name"),
            "album_art": album_art,
            "progress_ms": pb.get("progress_ms", 0),
            "duration_ms": item.get("duration_ms", 0),
            "uri": item.get("uri"),
        }
        _spotify_cache_ts = now
        return _spotify_cache_data
    except Exception as e:
        log.error(f"[nowplaying] {e}")
        if _spotify_cache_data:
            return _spotify_cache_data
        return {"playing": False}


@app.get("/search")
def search(q: str):
    """Search Spotify tracks."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query required")
    try:
        results = spotify_get("/search", params={"q": q, "type": "track", "limit": 10})
        if results is None:
            return {"tracks": [], "error": "Rate limited, try again in a moment"}
        tracks = []
        for item in results.get("tracks", {}).get("items", []):
            images = item.get("album", {}).get("images", [])
            tracks.append({
                "title": item["name"],
                "artist": item["artists"][0]["name"] if item.get("artists") else "Unknown",
                "album": item.get("album", {}).get("name"),
                "uri": item["uri"],
                "album_art": images[-1]["url"] if images else None,
                "duration_ms": item.get("duration_ms", 0),
            })
        return {"tracks": tracks}
    except Exception as e:
        log.error(f"[search] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/queue/add")
def queue_track(body: QueueRequest):
    """Add a track to Spotify queue."""
    try:
        spotify_post(f"/me/player/queue?uri={body.uri}")
        return {"status": "queued", "uri": body.uri}
    except Exception as e:
        log.error(f"[queue] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Playlist endpoints ---

@app.get("/playlists/search")
def search_playlists(q: str):
    """Search Spotify playlists."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query required")
    try:
        results = spotify_get("/search", params={"q": q, "type": "playlist", "limit": 8})
        if results is None:
            return {"playlists": [], "error": "Rate limited"}
        playlists = []
        for item in results.get("playlists", {}).get("items", []):
            if not item:
                continue
            images = item.get("images", [])
            tracks_field = item.get("tracks", {})
            track_count = tracks_field.get("total", 0) if isinstance(tracks_field, dict) else tracks_field
            playlists.append({
                "name": item["name"],
                "uri": item["uri"],
                "owner": item.get("owner", {}).get("display_name", ""),
                "tracks": track_count,
                "image": images[0]["url"] if images else None,
            })
        return {"playlists": playlists}
    except Exception as e:
        log.error(f"[playlist-search] {e}")
        raise HTTPException(status_code=500, detail=str(e))


class PlaylistRequest(BaseModel):
    uri: str


@app.post("/playlists/play")
def play_playlist(body: PlaylistRequest, _=Depends(require_bartender)):
    """Set a playlist as the current playback context."""
    try:
        spotify_put("/me/player/play", json_data={"context_uri": body.uri})
        log.info(f"[playlist] playing {body.uri}")
        return {"status": "playing", "uri": body.uri}
    except Exception as e:
        log.error(f"[playlist] {e}")
        raise HTTPException(status_code=500, detail=str(e))


_queue_cache_data = {"queue": []}
_queue_cache_ts = 0

@app.get("/queue")
def get_queue():
    """Get upcoming tracks from Spotify queue. Cached for 30s."""
    global _queue_cache_data, _queue_cache_ts
    try:
        now = _time.time()
        if now - _queue_cache_ts < 45 and _queue_cache_data.get("queue"):
            return _queue_cache_data
        data = spotify_get("/me/player/queue", block=False)
        if data is None:  # rate limited or throttled
            return _queue_cache_data
        if not data:
            return {"queue": []}
        tracks = []
        for item in data.get("queue", [])[:10]:
            images = item.get("album", {}).get("images", [])
            tracks.append({
                "title": item["name"],
                "artist": item["artists"][0]["name"] if item.get("artists") else "Unknown",
                "album_art": images[-1]["url"] if images else None,
            })
        _queue_cache_data = {"queue": tracks}
        _queue_cache_ts = now
        return _queue_cache_data
    except Exception as e:
        log.error(f"[queue-get] {e}")
        return _queue_cache_data


@app.get("/spotify/stats")
def spotify_stats():
    """Spotify API usage stats and rate limit history — API + scheduler combined."""
    now = _time.time()
    api_1m = sum(1 for t, _ in _api_calls if now - t < 60)
    api_10m = sum(1 for t, _ in _api_calls if now - t < 600)
    api_1h = len(_api_calls)

    api_endpoints = {}
    for t, ep in _api_calls:
        api_endpoints[ep] = api_endpoints.get(ep, 0) + 1

    # Scheduler stats (if running)
    try:
        from spotify_watcher import get_call_stats
        sched = get_call_stats()
    except Exception:
        sched = {"calls_last_1m": 0, "calls_last_10m": 0, "calls_last_1h": 0, "by_endpoint": {}}

    return {
        "api": {
            "calls_last_1m": api_1m,
            "calls_last_10m": api_10m,
            "calls_last_1h": api_1h,
            "by_endpoint": api_endpoints,
        },
        "scheduler": sched,
        "total": {
            "calls_last_1m": api_1m + sched["calls_last_1m"],
            "calls_last_10m": api_10m + sched["calls_last_10m"],
            "calls_last_1h": api_1h + sched["calls_last_1h"],
        },
        "rate_limits_hit": len(_rate_limit_log),
        "rate_limit_events": _rate_limit_log[-10:],
    }


# --- Mode (jukebox vs ai-dj) ---

_radio_mode = {"mode": "jukebox"}  # "jukebox" or "ai-dj"
_scheduler_proc = None


@app.get("/mode")
def get_mode():
    """Get current radio mode."""
    return _radio_mode


class ModeRequest(BaseModel):
    mode: str


@app.post("/mode")
def set_radio_mode(body: ModeRequest, _=Depends(require_bartender)):
    """Switch between jukebox (music only) and ai-dj (segments between songs)."""
    global _scheduler_proc
    if body.mode not in ("jukebox", "ai-dj"):
        raise HTTPException(status_code=400, detail="Mode must be 'jukebox' or 'ai-dj'")

    _radio_mode["mode"] = body.mode

    if body.mode == "ai-dj":
        # Start the scheduler if not running
        if _scheduler_proc is None or _scheduler_proc.poll() is not None:
            scheduler_path = Path(DRIFT_RADIO_DIR) / "engine" / "scheduler.py"
            if scheduler_path.exists():
                _scheduler_proc = subprocess.Popen(
                    [sys.executable, str(scheduler_path)],
                    cwd=str(scheduler_path.parent),
                )
                log.info(f"[mode] Started AI DJ scheduler (pid={_scheduler_proc.pid})")
            else:
                log.warning(f"[mode] Scheduler not found at {scheduler_path}")
    else:
        # Kill the scheduler if running
        if _scheduler_proc and _scheduler_proc.poll() is None:
            _scheduler_proc.terminate()
            log.info("[mode] Stopped AI DJ scheduler")
            _scheduler_proc = None

    log.info(f"[mode] Switched to {body.mode}")
    return _radio_mode


@app.post("/spotify/pause")
def spotify_pause(_=Depends(require_bartender)):
    """Pause Spotify playback (through throttle)."""
    try:
        result = spotify_put("/me/player/pause")
        if result is None:
            return {"status": "rate_limited"}
        return {"status": "paused"}
    except Exception as e:
        log.error(f"[spotify/pause] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/spotify/resume")
def spotify_resume(_=Depends(require_bartender)):
    """Resume Spotify playback (through throttle)."""
    try:
        result = spotify_put("/me/player/play")
        if result is None:
            return {"status": "rate_limited"}
        return {"status": "resumed"}
    except Exception as e:
        log.error(f"[spotify/resume] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nowplaying/live")
def now_playing_live():
    """Uncached nowplaying — for scheduler end-of-song detection. Still throttled."""
    global _spotify_cache_data, _spotify_cache_ts
    try:
        pb = spotify_get("/me/player")
        if pb is None:
            if _spotify_cache_data:
                return _spotify_cache_data
            return {"playing": False}
        if not pb or not pb.get("item"):
            return {"playing": False}
        item = pb["item"]
        images = item.get("album", {}).get("images", [])
        album_art = images[0]["url"] if images else None
        data = {
            "playing": pb.get("is_playing", False),
            "artist": item["artists"][0]["name"] if item.get("artists") else "Unknown",
            "track": item["name"],
            "album": item.get("album", {}).get("name"),
            "album_art": album_art,
            "progress_ms": pb.get("progress_ms", 0),
            "duration_ms": item.get("duration_ms", 0),
            "uri": item.get("uri"),
        }
        # Also update the cache since we made a fresh call anyway
        _spotify_cache_data = data
        _spotify_cache_ts = _time.time()
        return data
    except Exception as e:
        log.error(f"[nowplaying/live] {e}")
        if _spotify_cache_data:
            return _spotify_cache_data
        return {"playing": False}


@app.get("/status")
def status():
    """Icecast listener count + stream status."""
    icecast_url = os.getenv("ICECAST_STATUS_URL", "http://localhost:8000/status-json.xsl")
    try:
        resp = requests.get(icecast_url, timeout=5)
        data = resp.json()
        sources = data.get("icestats", {}).get("source", [])
        if isinstance(sources, dict):
            sources = [sources]
        listeners = sum(s.get("listeners", 0) for s in sources)
        return {"online": True, "listeners": listeners}
    except Exception:
        return {"online": False, "listeners": 0}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8080, reload=True, workers=4)
