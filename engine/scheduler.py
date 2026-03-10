#!/usr/bin/env python3
"""
drift-radio main scheduler.

Segment budget per hour:
  - 1 news break (generated at :50, queued to play at top of hour)
  - 2 song facts max (generated at song start, queued near song end)

Song fact flow:
  1. Track changes → check if we have budget → start generating in background
  2. Poll remaining time while generating
  3. Segment ready + song has <QUEUE_THRESHOLD_S remaining → queue it
  4. Segment ready but song has lots of time left → wait
  5. Song ends before segment ready → hold segment, queue after next track starts
"""

import threading
import time
import logging
import os
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

# How many seconds from end of song to queue the segment
QUEUE_THRESHOLD_S = 15

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


# --- Listener check ---

def has_listeners() -> bool:
    try:
        resp = requests.get(config.ICECAST_STATUS_URL, timeout=5)
        data = resp.json()
        sources = data.get("icestats", {}).get("source", [])
        if isinstance(sources, dict):
            sources = [sources]
        return sum(s.get("listeners", 0) for s in sources) > 0
    except Exception:
        return True  # assume listeners if we can't check


# --- Segment cleanup ---

def cleanup_segments():
    segs = sorted(Path(config.SEGMENTS_DIR).glob("*.mp3"), key=os.path.getmtime)
    for old in segs[: max(0, len(segs) - config.SEGMENTS_KEEP)]:
        try:
            old.unlink()
        except Exception:
            pass


# --- Song fact: smart queuing ---

def _wait_and_queue_song_fact(future: Future, sp, track):
    """
    Wait for generation to finish, then wait for the right moment to queue.
    Right moment = song has <= QUEUE_THRESHOLD_S remaining.
    If song ends before segment is ready, queue immediately when next song starts.
    """
    log.info(f"[scheduler] waiting for segment generation ({track})")

    # Block until generation done
    try:
        segment_path = future.result(timeout=config.CLAUDE_TIMEOUT + 30)
    except Exception as e:
        log.error(f"[scheduler] song fact generation failed: {e}")
        return

    if not segment_path or not Path(segment_path).exists():
        log.error("[scheduler] segment path missing after generation")
        return

    log.info(f"[scheduler] segment ready: {segment_path.name}, waiting for queue window")

    # Poll remaining time, queue when <= threshold
    deadline = time.time() + 600  # give up after 10 min (next song etc)
    while time.time() < deadline:
        state = spotify_watcher.get_playback(sp)

        if not state.is_playing:
            # Playback stopped — queue now, it'll play next
            log.info("[scheduler] playback stopped, queuing segment now")
            break

        if state.track and state.track != track:
            # Song already changed — we missed the window, queue now for current song
            log.info("[scheduler] song changed before queue window, queuing for current track")
            break

        remaining = state.remaining_s
        log.debug(f"[scheduler] remaining: {remaining:.1f}s (threshold: {QUEUE_THRESHOLD_S}s)")

        if remaining <= QUEUE_THRESHOLD_S:
            log.info(f"[scheduler] {remaining:.1f}s left — queuing segment")
            break

        time.sleep(2)

    liquidsoap_queue.push_segment(segment_path)
    cleanup_segments()


def on_track_change(prev, curr, sp):
    global _song_facts_this_hour
    _reset_hourly_counters()

    if _song_facts_this_hour >= MAX_SONG_FACTS_PER_HOUR:
        log.info(f"[scheduler] song fact budget exhausted ({_song_facts_this_hour}/{MAX_SONG_FACTS_PER_HOUR}), skipping")
        return

    if not has_listeners():
        log.info("[scheduler] no listeners, skipping song fact")
        return

    log.info(f"[scheduler] generating song fact for: {curr} "
             f"({_song_facts_this_hour + 1}/{MAX_SONG_FACTS_PER_HOUR} this hour)")
    _song_facts_this_hour += 1

    # Start generation immediately in background
    future = executor.submit(segment_generator.song_fact, curr.artist, curr.title)

    # Watch and queue in a separate thread
    threading.Thread(
        target=_wait_and_queue_song_fact,
        args=(future, sp, curr),
        daemon=True,
    ).start()


# --- News break: generate at :50, plays at top of hour ---

_news_generated_this_hour = False


def check_schedule():
    global _news_this_hour, _news_generated_this_hour
    _reset_hourly_counters()

    minute = datetime.now().minute

    # Reset flag at top of hour
    if minute < 5:
        _news_generated_this_hour = False

    # Generate news at :50 so it's ready by :00
    if minute == 50 and not _news_generated_this_hour:
        if _news_this_hour >= MAX_NEWS_PER_HOUR:
            log.info("[scheduler] news budget exhausted, skipping")
            return
        if has_listeners():
            log.info("[scheduler] :50 → generating news break (will play after current track near :00)")
            _news_generated_this_hour = True
            _news_this_hour += 1
            executor.submit(_generate_and_queue, segment_generator.news_break)


def _generate_and_queue(fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        if isinstance(result, list):
            for path in result:
                liquidsoap_queue.push_segment(path)
        else:
            liquidsoap_queue.push_segment(result)
        cleanup_segments()
    except Exception as e:
        log.error(f"[scheduler] {fn.__name__} failed: {e}")


# --- Main ---

def main():
    log.info("=== drift-radio scheduler starting ===")
    log.info(f"    song facts: max {MAX_SONG_FACTS_PER_HOUR}/hr")
    log.info(f"    news breaks: max {MAX_NEWS_PER_HOUR}/hr (generated at :50)")
    Path(config.LOGS_DIR).mkdir(exist_ok=True)
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
