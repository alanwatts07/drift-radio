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

# Add drift-radio to path so we can reuse tts_renderer + liquidsoap_queue
DRIFT_RADIO_DIR = os.getenv("DRIFT_RADIO_DIR", "/home/morpheus/Hackstuff/drift-radio")
sys.path.insert(0, DRIFT_RADIO_DIR)
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


# --- Models ---

class RawAnnouncement(BaseModel):
    text: str

class AIAnnouncement(BaseModel):
    prompt: str

class QueueRequest(BaseModel):
    uri: str


# --- Announce endpoints ---

@app.post("/announce/raw")
async def announce_raw(body: RawAnnouncement, _=Depends(require_bartender)):
    """Play text verbatim on air."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    log.info(f"[announce/raw] {body.text[:60]}")
    out = SEGMENTS_DIR / "announce_raw.mp3"

    try:
        tts_renderer.render(body.text, out)
        liquidsoap_queue.push_segment(out)
    except Exception as e:
        log.error(f"[announce/raw] failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "queued", "text": body.text}


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
    prompt = f"{system}\n\nAnnouncement topic: {body.prompt}"

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--max-turns", "1"],
            capture_output=True, text=True, timeout=60,
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
        liquidsoap_queue.push_segment(out)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "queued", "script": script}


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
    """Spotify API usage stats and rate limit history."""
    now = _time.time()
    calls_1m = sum(1 for t, _ in _api_calls if now - t < 60)
    calls_10m = sum(1 for t, _ in _api_calls if now - t < 600)
    calls_1h = len(_api_calls)

    # Breakdown by endpoint
    endpoint_counts = {}
    for t, ep in _api_calls:
        endpoint_counts[ep] = endpoint_counts.get(ep, 0) + 1

    return {
        "calls_last_1m": calls_1m,
        "calls_last_10m": calls_10m,
        "calls_last_1h": calls_1h,
        "by_endpoint": endpoint_counts,
        "rate_limits_hit": len(_rate_limit_log),
        "rate_limit_events": _rate_limit_log[-10:],  # last 10 events
    }


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
