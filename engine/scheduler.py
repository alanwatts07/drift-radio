#!/usr/bin/env python3
"""
drift-radio main scheduler.

Segment budget per hour:
  - 1 news break (generated at :50, queued to play at top of hour)
  - 2 song facts max (generated at song start, plays between songs)

Playback flow:
  1. Song fact: generate during current song, store it
  2. When track changes: pause Spotify → push segment → wait for duration → resume
  3. News: generate at :50, store it, play at next track change after :00
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


def _play_segment(sp, segment_path: Path):
    """Pause Spotify → push segment → wait for it to finish → resume Spotify."""
    duration = _get_mp3_duration(segment_path)
    log.info(f"[scheduler] playing segment: {segment_path.name} ({duration:.1f}s)")

    spotify_watcher.pause(sp)
    time.sleep(0.5)  # let harbor go silent

    liquidsoap_queue.push_segment(segment_path, priority=True)
    time.sleep(duration + 1)  # wait for segment to finish (+1s buffer)

    spotify_watcher.resume(sp)
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


def _drain_pending(sp, prev_track):
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
            _play_segment(sp, seg_path)


# --- Song fact generation ---

def _generate_song_fact(artist: str, title: str, uri: str):
    """Generate song fact in background, add to pending tagged with song URI."""
    try:
        path = segment_generator.song_fact(artist, title)
        if path and Path(path).exists():
            _add_pending(Path(path), song_uri=uri)
    except Exception as e:
        log.error(f"[scheduler] song fact generation failed: {e}")


def on_track_change(prev, curr, sp):
    global _song_facts_this_hour
    _reset_hourly_counters()

    # First, play any pending segments — song facts only if prev matches
    _drain_pending(sp, prev)

    # Then start generating a fact for the new song
    if _song_facts_this_hour >= MAX_SONG_FACTS_PER_HOUR:
        log.info(f"[scheduler] song fact budget exhausted ({_song_facts_this_hour}/{MAX_SONG_FACTS_PER_HOUR})")
        return

    if not has_listeners():
        log.info("[scheduler] no listeners, skipping song fact")
        return

    _song_facts_this_hour += 1
    _generating_for = curr.uri
    log.info(f"[scheduler] generating song fact for: {curr} "
             f"({_song_facts_this_hour}/{MAX_SONG_FACTS_PER_HOUR} this hour)")

    executor.submit(_generate_song_fact, curr.artist, curr.title, curr.uri)


# --- News break ---

_news_generated_this_hour = False
_news_pending_path: Path | None = None


def check_schedule():
    global _news_this_hour, _news_generated_this_hour, _news_pending_path
    _reset_hourly_counters()

    minute = datetime.now().minute

    # Reset flag at top of hour
    if minute < 5:
        _news_generated_this_hour = False

    # Generate news at :50 so it's ready by :00
    if minute == 50 and not _news_generated_this_hour:
        if _news_this_hour >= MAX_NEWS_PER_HOUR:
            return
        if has_listeners():
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
    log.info(f"    song facts: max {MAX_SONG_FACTS_PER_HOUR}/hr")
    log.info(f"    news breaks: max {MAX_NEWS_PER_HOUR}/hr (generated at :50)")
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
