#!/usr/bin/env python3
"""
drift-radio main scheduler.

Segment schedule per hour:
  - :20 — song fact #1 (generate for current song, play at next track change)
  - :40 — song fact #2 (generate for current song, play at next track change)
  - :50 — news break (generate, play at next track change after :00)

Playback flow:
  1. check_schedule() triggers generation at :20, :40, :50
  2. Segments stored as pending, tagged with song URI (facts) or None (news)
  3. On track change: pause Spotify → play pending segments → resume
"""

import threading
import time
import logging
import os
import subprocess
import requests
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, Future

from dotenv import load_dotenv
load_dotenv()

import config
import segment_generator
import liquidsoap_queue
import spotify_watcher

Path(config.LOGS_DIR).mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(config.LOGS_DIR) / "scheduler.log"),
    ],
)
log = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=3)

# --- Rate limiting ---
MAX_SONG_FACTS_PER_HOUR = 2
MAX_NEWS_PER_HOUR = 1

_song_facts_this_hour = 0
_news_this_hour = 0
_current_hour = datetime.now().hour


def _reset_hourly_counters():
    """Reset counters at the top of each hour."""
    global _song_facts_this_hour, _news_this_hour, _current_hour
    hour = datetime.now().hour
    if hour != _current_hour:
        log.info(f"[scheduler] new hour ({hour:02d}:00) — resetting counters "
                 f"(song facts: {_song_facts_this_hour}, news: {_news_this_hour})")
        _song_facts_this_hour = 0
        _news_this_hour = 0
        _current_hour = hour


# --- Helpers ---

def has_listeners() -> bool:
    try:
        resp = requests.get(config.ICECAST_STATUS_URL, timeout=5)
        data = resp.json()
        sources = data.get("icestats", {}).get("source", [])
        if isinstance(sources, dict):
            sources = [sources]
        return sum(s.get("listeners", 0) for s in sources) > 0
    except Exception:
        return True


def cleanup_segments():
    segs = sorted(Path(config.SEGMENTS_DIR).glob("*.mp3"), key=os.path.getmtime)
    for old in segs[: max(0, len(segs) - config.SEGMENTS_KEEP)]:
        try:
            old.unlink()
        except Exception:
            pass


def _get_mp3_duration(path: Path) -> float:
    """Get duration of mp3 in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception as e:
        log.warning(f"[scheduler] ffprobe failed for {path}: {e}")
        return 30.0  # safe fallback


def _play_segment(segment_path: Path):
    """Pause Spotify → push segment → wait for it to finish → resume Spotify."""
    duration = _get_mp3_duration(segment_path)
    log.info(f"[scheduler] playing segment: {segment_path.name} ({duration:.1f}s)")

    spotify_watcher.pause()
    time.sleep(0.3)  # let harbor go silent

    liquidsoap_queue.push_segment(segment_path, priority=True)
    # Resume Spotify ~7s before segment ends — accounts for TTS trailing
    # silence + Spotify resume latency. Slightly early beats dead air.
    time.sleep(max(0, duration - 7))

    spotify_watcher.resume()
    log.info(f"[scheduler] segment done, Spotify resumed")
    cleanup_segments()


# --- Pending segments ---
# Segments generated during a song, waiting to play at next track change
# Each entry: (path, song_uri_or_None)
# song_uri is set for song facts (skip if song was skipped), None for news (always play)

_pending_lock = threading.Lock()
_pending_segments: list[tuple[Path, str | None]] = []


def _add_pending(path: Path, song_uri: str | None = None):
    with _pending_lock:
        _pending_segments.append((path, song_uri))
        log.info(f"[scheduler] segment ready, pending: {path.name}")


def _drain_pending(prev_track):
    """Play pending segments. Song facts only play if they match the song that just ended."""
    with _pending_lock:
        segments = list(_pending_segments)
        _pending_segments.clear()

    if not segments:
        return

    prev_uri = prev_track.uri if prev_track else None
    for seg_path, song_uri in segments:
        if song_uri and prev_uri and song_uri != prev_uri:
            log.info(f"[scheduler] skipping stale segment {seg_path.name} (song was skipped)")
            continue
        if seg_path.exists():
            _play_segment(seg_path)


# --- Song fact generation ---

# Track the current song so check_schedule can generate facts for it
_current_track_lock = threading.Lock()
_current_track = None  # spotify_watcher.Track

def _generate_song_fact(artist: str, title: str, uri: str):
    """Generate song fact in background, add to pending tagged with song URI."""
    try:
        path = segment_generator.song_fact(artist, title)
        if path and Path(path).exists():
            _add_pending(Path(path), song_uri=uri)
    except Exception as e:
        log.error(f"[scheduler] song fact generation failed: {e}")


def on_track_change(prev, curr, sp=None):
    global _current_track
    _reset_hourly_counters()

    # Update current track reference for check_schedule
    with _current_track_lock:
        _current_track = curr

    # Play any pending segments — song facts only if prev matches
    _drain_pending(prev)


# --- Scheduled generation ---
# Song facts at :20 and :40, news at :50
# Each generates during that minute, then plays at the next track change

_fact_generated_at_20 = False
_fact_generated_at_40 = False
_news_generated_this_hour = False


def check_schedule():
    global _song_facts_this_hour, _news_this_hour
    global _fact_generated_at_20, _fact_generated_at_40, _news_generated_this_hour
    _reset_hourly_counters()

    minute = datetime.now().minute

    # Reset flags at top of hour
    if minute < 5:
        _fact_generated_at_20 = False
        _fact_generated_at_40 = False
        _news_generated_this_hour = False

    if not has_listeners():
        return

    # Song fact #1 at :20
    if 20 <= minute < 25 and not _fact_generated_at_20:
        with _current_track_lock:
            track = _current_track
        if track:
            _fact_generated_at_20 = True
            _song_facts_this_hour += 1
            log.info(f"[scheduler] :20 → generating song fact for: {track} "
                     f"({_song_facts_this_hour}/{MAX_SONG_FACTS_PER_HOUR} this hour)")
            executor.submit(_generate_song_fact, track.artist, track.title, track.uri)

    # Song fact #2 at :40
    if 40 <= minute < 45 and not _fact_generated_at_40:
        with _current_track_lock:
            track = _current_track
        if track:
            _fact_generated_at_40 = True
            _song_facts_this_hour += 1
            log.info(f"[scheduler] :40 → generating song fact for: {track} "
                     f"({_song_facts_this_hour}/{MAX_SONG_FACTS_PER_HOUR} this hour)")
            executor.submit(_generate_song_fact, track.artist, track.title, track.uri)

    # News at :50
    if 50 <= minute < 55 and not _news_generated_this_hour:
        if _news_this_hour < MAX_NEWS_PER_HOUR:
            log.info("[scheduler] :50 → generating news break")
            _news_generated_this_hour = True
            _news_this_hour += 1
            executor.submit(_generate_news)


def _generate_news():
    """Generate news and add to pending segments."""
    try:
        path = segment_generator.news_break()
        if path and Path(path).exists():
            _add_pending(Path(path))
    except Exception as e:
        log.error(f"[scheduler] news generation failed: {e}")


# --- Main ---

def main():
    log.info("=== drift-radio scheduler starting ===")
    log.info(f"    song facts: at :20 and :40 (max {MAX_SONG_FACTS_PER_HOUR}/hr)")
    log.info(f"    news breaks: at :50 (max {MAX_NEWS_PER_HOUR}/hr)")
    Path(config.SEGMENTS_DIR).mkdir(exist_ok=True)

    stop_event = threading.Event()

    spotify_thread = threading.Thread(
        target=spotify_watcher.watch,
        args=(on_track_change,),
        kwargs={"stop_event": stop_event},
        daemon=True,
    )
    spotify_thread.start()

    try:
        while True:
            check_schedule()
            time.sleep(10)
    except KeyboardInterrupt:
        log.info("Shutting down...")
        stop_event.set()
        executor.shutdown(wait=False)


if __name__ == "__main__":
    main()
