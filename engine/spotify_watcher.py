#!/usr/bin/env python3
"""
Spotify watcher — track change detection + playback state.
Provides remaining time so scheduler can queue segments at the right moment.
"""

import time
import logging
import os
from dataclasses import dataclass
import spotipy
from spotipy.oauth2 import SpotifyOAuth

from collections import deque

import config

log = logging.getLogger(__name__)

# --- Call tracking (shared with API via /spotify/stats) ---
_calls = deque()  # timestamps of all Spotify API calls from scheduler

def _track(endpoint: str):
    now = time.time()
    _calls.append((now, endpoint))
    # Prune older than 1 hour
    cutoff = now - 3600
    while _calls and _calls[0][0] < cutoff:
        _calls.popleft()

def get_call_stats() -> dict:
    """Return scheduler Spotify API call stats."""
    now = time.time()
    calls_1m = sum(1 for t, _ in _calls if now - t < 60)
    calls_10m = sum(1 for t, _ in _calls if now - t < 600)
    calls_1h = len(_calls)
    by_endpoint = {}
    for t, ep in _calls:
        by_endpoint[ep] = by_endpoint.get(ep, 0) + 1
    return {
        "calls_last_1m": calls_1m,
        "calls_last_10m": calls_10m,
        "calls_last_1h": calls_1h,
        "by_endpoint": by_endpoint,
    }

SCOPE = "user-read-playback-state user-read-currently-playing user-modify-playback-state"


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


def _make_sp() -> spotipy.Spotify:
    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=os.getenv("SPOTIFY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
            redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
            scope=SCOPE,
            cache_path=".spotify_cache",
        )
    )


def get_playback(sp: spotipy.Spotify) -> PlaybackState:
    try:
        _track("current_playback")
        pb = sp.current_playback()
        if not pb or not pb.get("item"):
            return PlaybackState(track=None, progress_ms=0, is_playing=False)
        item = pb["item"]
        artist = item["artists"][0]["name"] if item.get("artists") else "Unknown"
        track = Track(
            artist=artist,
            title=item["name"],
            uri=item["uri"],
            duration_ms=item["duration_ms"],
        )
        return PlaybackState(
            track=track,
            progress_ms=pb.get("progress_ms", 0),
            is_playing=pb.get("is_playing", False),
        )
    except Exception as e:
        log.warning(f"[spotify] playback fetch failed: {e}")
        return PlaybackState(track=None, progress_ms=0, is_playing=False)


def pause(sp: spotipy.Spotify):
    """Pause Spotify playback."""
    try:
        _track("pause")
        sp.pause_playback()
        log.info("[spotify] paused")
    except Exception as e:
        log.warning(f"[spotify] pause failed: {e}")


def resume(sp: spotipy.Spotify):
    """Resume Spotify playback."""
    try:
        _track("resume")
        sp.start_playback()
        log.info("[spotify] resumed")
    except Exception as e:
        log.warning(f"[spotify] resume failed: {e}")


def watch(on_track_change, stop_event=None):
    """
    Smart polling: check once to get track + remaining time, sleep until
    ~15s before end, then rapid-poll every 3s to catch the exact change.
    Minimizes API calls (~5-10 per song instead of hundreds).
    """
    sp = _make_sp()
    state = get_playback(sp)
    current = state.track
    log.info(f"[spotify] watching — current: {current}")

    while True:
        if stop_event and stop_event.is_set():
            break

        state = get_playback(sp)

        if not state.is_playing or not state.track:
            # Nothing playing — slow poll
            time.sleep(30)
            continue

        if state.track != current:
            # Track changed while we were sleeping
            prev = current
            current = state.track
            log.info(f"[spotify] track changed: {prev} → {current}")
            try:
                on_track_change(prev, current, sp)
            except Exception as e:
                log.error(f"[spotify] on_track_change error: {e}")
            continue

        # Sleep until ~5s before song ends, then verify same song before rapid-poll
        remaining = state.remaining_s
        if remaining > 8:
            sleep_for = remaining - 5
            log.debug(f"[spotify] {remaining:.0f}s left, sleeping {sleep_for:.0f}s")
            time.sleep(sleep_for)

            # After waking, verify it's still the same song before burning API calls
            check = get_playback(sp)
            if not check.track or check.track != current:
                # Song changed while sleeping — loop back, top of loop will handle it
                continue
        else:
            # Final 5s — poll every 1s to catch the exact change
            time.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    def on_change(prev, curr, sp):
        print(f"Track change: {prev} → {curr}")
        state = get_playback(sp)
        print(f"Remaining: {state.remaining_s:.1f}s")

    watch(on_change)
