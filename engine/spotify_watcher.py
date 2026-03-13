#!/usr/bin/env python3
"""
Spotify watcher — track change detection + playback state.
Routes ALL Spotify calls through the FTR API so everything shares one throttle.
"""

import time
import logging
import os
from dataclasses import dataclass

import requests

import config

log = logging.getLogger(__name__)

API_BASE = os.getenv("FTR_API_URL", "http://localhost:8080")
BARTENDER_PASSWORD = os.getenv("BARTENDER_PASSWORD", "ftr2024")


@dataclass
class Track:
    artist: str
    title: str
    uri: str
    duration_ms: int

    def __str__(self):
        return f"{self.artist} - {self.title}"

    def __eq__(self, other):
        return isinstance(other, Track) and self.uri == other.uri


@dataclass
class PlaybackState:
    track: Track | None
    progress_ms: int
    is_playing: bool

    @property
    def remaining_ms(self) -> int:
        if self.track is None:
            return 0
        return max(0, self.track.duration_ms - self.progress_ms)

    @property
    def remaining_s(self) -> float:
        return self.remaining_ms / 1000


def _api_get(path: str) -> dict | None:
    """GET from the FTR API."""
    try:
        resp = requests.get(f"{API_BASE}{path}", timeout=15)
        return resp.json()
    except Exception as e:
        log.warning(f"[watcher] API GET {path} failed: {e}")
        return None


def _api_post(path: str) -> dict | None:
    """POST to the FTR API with bartender auth."""
    try:
        resp = requests.post(
            f"{API_BASE}{path}",
            headers={"x-password": BARTENDER_PASSWORD},
            timeout=15,
        )
        return resp.json()
    except Exception as e:
        log.warning(f"[watcher] API POST {path} failed: {e}")
        return None


def get_playback_from_api(live: bool = False) -> PlaybackState:
    """Get playback state from the API. live=True bypasses cache."""
    endpoint = "/nowplaying/live" if live else "/nowplaying"
    data = _api_get(endpoint)
    if not data or not data.get("playing"):
        return PlaybackState(track=None, progress_ms=0, is_playing=False)
    track = Track(
        artist=data.get("artist", "Unknown"),
        title=data.get("track", "Unknown"),
        uri=data.get("uri", ""),
        duration_ms=data.get("duration_ms", 0),
    )
    return PlaybackState(
        track=track,
        progress_ms=data.get("progress_ms", 0),
        is_playing=data.get("playing", False),
    )


def pause(sp=None):
    """Pause Spotify via API."""
    result = _api_post("/spotify/pause")
    if result and result.get("status") == "paused":
        log.info("[watcher] paused via API")
    else:
        log.warning(f"[watcher] pause result: {result}")


def resume(sp=None):
    """Resume Spotify via API."""
    result = _api_post("/spotify/resume")
    if result and result.get("status") == "resumed":
        log.info("[watcher] resumed via API")
    else:
        log.warning(f"[watcher] resume result: {result}")


# Keep get_playback compatible for scheduler imports
def get_playback(sp=None) -> PlaybackState:
    return get_playback_from_api(live=False)


def get_call_stats() -> dict:
    """Return empty stats — all calls now go through the API's tracking."""
    return {
        "calls_last_1m": 0,
        "calls_last_10m": 0,
        "calls_last_1h": 0,
        "by_endpoint": {},
        "rate_limit": {
            "calls_per_min": 0,
            "limit": 180,
            "remaining_estimate": 180,
            "status": "ok",
            "backing_off": False,
        },
    }


def watch(on_track_change, stop_event=None):
    """
    Watch for track changes by polling the API.
    Uses cached /nowplaying most of the time, /nowplaying/live near song end.
    All Spotify calls go through the API's throttle.
    """
    state = get_playback_from_api(live=True)
    current = state.track
    log.info(f"[watcher] watching — current: {current}")

    while True:
        if stop_event and stop_event.is_set():
            break

        # Use cached endpoint for normal polling
        state = get_playback_from_api(live=False)

        if not state.is_playing or not state.track:
            time.sleep(30)
            continue

        if state.track != current:
            prev = current
            current = state.track
            log.info(f"[watcher] track changed: {prev} → {current}")
            try:
                on_track_change(prev, current, None)
            except Exception as e:
                log.error(f"[watcher] on_track_change error: {e}")
            continue

        # Sleep based on remaining time
        remaining = state.remaining_s

        if remaining > 20:
            # Long way to go — sleep most of it, use cached endpoint
            sleep_for = remaining - 15
            log.debug(f"[watcher] {remaining:.0f}s left, sleeping {sleep_for:.0f}s")
            time.sleep(sleep_for)
        elif remaining > 5:
            # Getting close — use live endpoint to get fresh data
            time.sleep(10)
            state = get_playback_from_api(live=True)
            if state.track and state.track != current:
                prev = current
                current = state.track
                log.info(f"[watcher] track changed: {prev} → {current}")
                try:
                    on_track_change(prev, current, None)
                except Exception as e:
                    log.error(f"[watcher] on_track_change error: {e}")
        else:
            # Final seconds — one more live check then wait
            time.sleep(10)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    def on_change(prev, curr, sp):
        print(f"Track change: {prev} → {curr}")

    watch(on_change)
