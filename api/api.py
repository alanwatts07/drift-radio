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
from collections import deque

_spotify_cache_data = {}  # in-memory cache for nowplaying
_spotify_cache_ts = 0

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

def spotify_get(path: str, params: dict = None) -> dict:
    _track_call(path)
    token = _refresh_spotify_token()
    resp = requests.get(f"{SPOTIFY_API}{path}", headers={"Authorization": f"Bearer {token}"}, params=params, timeout=10)
    if resp.status_code == 204:
        return {}
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 5))
        _track_429(path, retry_after)
        return None
    resp.raise_for_status()
    return resp.json()

def spotify_post(path: str, json_data: dict = None) -> dict:
    _track_call(path)
    token = _refresh_spotify_token()
    resp = requests.post(f"{SPOTIFY_API}{path}", headers={"Authorization": f"Bearer {token}"}, json=json_data, timeout=10)
    if resp.status_code == 204:
        return {}
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 5))
        _track_429(path, retry_after)
        return None
    resp.raise_for_status()
    return resp.json()

def spotify_put(path: str, json_data: dict = None) -> dict:
    _track_call(path)
    token = _refresh_spotify_token()
    resp = requests.put(f"{SPOTIFY_API}{path}", headers={"Authorization": f"Bearer {token}"}, json=json_data, timeout=10)
    if resp.status_code == 204:
        return {}
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 5))
        _track_429(path, retry_after)
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

class QueueRequest(BaseModel):
    uri: str


# --- Announce endpoints ---

@app.post("/announce/raw")
async def announce_raw(body: RawAnnouncement, _=Depends(require_bartender)):
    """Play text verbatim on air."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    log.info(f"[announce/raw] {'NOW ' if body.now else ''}{body.text[:60]}")
    out = SEGMENTS_DIR / "announce_raw.mp3"

    try:
        tts_renderer.render(body.text, out)
        if body.now:
            liquidsoap_queue.push_segment(out, priority=True)
        else:
            liquidsoap_queue.push_segment(out)
    except Exception as e:
        log.error(f"[announce/raw] failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "playing now" if body.now else "queued", "text": body.text}


@app.post("/announce/ai")
async def announce_ai(body: AIAnnouncement, _=Depends(require_bartender)):
    """Claude generates a script from prompt, plays it on air."""
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    log.info(f"[announce/ai] prompt: {body.prompt[:60]}")

    system = (
        "You are a dry, deadpan radio host for a bar called FTR (Fun Time Radio). "
        "Write a short, punchy on-air announcement (max 20 seconds when read aloud). "
        "No filler, no fake enthusiasm. Just say the thing. Output only the script."
    )

    try:
        # Use Claude CLI with nested session check bypassed
        env = {**os.environ}
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_CODE", None)
        result = subprocess.run(
            [
                "claude", "-p", f"Announcement topic: {body.prompt}",
                "--system-prompt", system,
                "--max-turns", "1",
            ],
            capture_output=True, text=True, timeout=60,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr[:200])
        script = result.stdout.strip()
    except Exception as e:
        log.error(f"[announce/ai] Claude failed: {e}")
        raise HTTPException(status_code=500, detail=f"Claude error: {e}")

    out = SEGMENTS_DIR / "announce_ai.mp3"
    try:
        tts_renderer.render(script, out)
        if body.now:
            liquidsoap_queue.push_segment(out, priority=True)
        else:
            liquidsoap_queue.push_segment(out)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "playing now" if body.now else "queued", "script": script}


# --- Spotify endpoints ---

@app.get("/nowplaying")
async def now_playing():
    """Current track info + album art. Cached for 5s to avoid rate limits."""
    global _spotify_cache_data, _spotify_cache_ts
    try:
        now = _time.time()
        if now - _spotify_cache_ts < 10 and _spotify_cache_data:
            return _spotify_cache_data
        pb = spotify_get("/me/player")
        if pb is None:  # rate limited
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
async def search(q: str):
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
async def queue_track(body: QueueRequest):
    """Add a track to Spotify queue."""
    try:
        spotify_post(f"/me/player/queue?uri={body.uri}")
        return {"status": "queued", "uri": body.uri}
    except Exception as e:
        log.error(f"[queue] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Playlist endpoints ---

@app.get("/playlists/search")
async def search_playlists(q: str):
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
            playlists.append({
                "name": item["name"],
                "uri": item["uri"],
                "owner": item.get("owner", {}).get("display_name", ""),
                "tracks": item.get("tracks", {}).get("total", 0),
                "image": images[0]["url"] if images else None,
            })
        return {"playlists": playlists}
    except Exception as e:
        log.error(f"[playlist-search] {e}")
        raise HTTPException(status_code=500, detail=str(e))


class PlaylistRequest(BaseModel):
    uri: str


@app.post("/playlists/play")
async def play_playlist(body: PlaylistRequest, _=Depends(require_bartender)):
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
async def get_queue():
    """Get upcoming tracks from Spotify queue. Cached for 30s."""
    global _queue_cache_data, _queue_cache_ts
    try:
        now = _time.time()
        if now - _queue_cache_ts < 30 and _queue_cache_data.get("queue"):
            return _queue_cache_data
        data = spotify_get("/me/player/queue")
        if data is None:  # rate limited
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
async def spotify_stats():
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
async def get_mode():
    """Get current radio mode."""
    return _radio_mode


class ModeRequest(BaseModel):
    mode: str


@app.post("/mode")
async def set_radio_mode(body: ModeRequest, _=Depends(require_bartender)):
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


@app.get("/status")
async def status():
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
    uvicorn.run("api:app", host="0.0.0.0", port=8080, reload=True)
