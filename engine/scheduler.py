#!/usr/bin/env python3
"""
drift-radio main scheduler.

Song fact flow:
  1. Track changes → immediately start generating segment in background
  2. Poll remaining time while generating
  3. Segment ready + song has <QUEUE_THRESHOLD_S remaining → queue it
  4. Segment ready but song has lots of time left → wait
  5. Song ends before segment ready → hold segment, queue after next track starts
"""

import threading
import time
import logging
import random
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
            log.info(f"[scheduler] song changed before queue window, queuing for current track")
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
    if not has_listeners():
        log.info("[scheduler] no listeners, skipping song fact")
        return

    log.info(f"[scheduler] generating song fact for: {curr}")

    # Start generation immediately in background
    future = executor.submit(segment_generator.song_fact, curr.artist, curr.title)

    # Watch and queue in a separate thread
    threading.Thread(
        target=_wait_and_queue_song_fact,
        args=(future, sp, curr),
        daemon=True,
    ).start()


# --- Scheduled segments ---

_last_minute_fired: int | None = None


def check_schedule():
    global _last_minute_fired
    minute = datetime.now().minute

    if minute == _last_minute_fired:
        return

    if minute == config.SCHEDULE["full_broadcast_minute"]:
        if has_listeners():
            log.info("[scheduler] :00 → full broadcast")
            executor.submit(_generate_and_queue, segment_generator.full_broadcast)
        _last_minute_fired = minute

    elif minute == config.SCHEDULE["news_break_minute"]:
        if has_listeners():
            log.info("[scheduler] :30 → news break")
            executor.submit(_generate_and_queue, segment_generator.news_break)
        _last_minute_fired = minute


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


# --- Random agent commentary ---

_last_agent_time: float = 0
AGENT_INTERVAL_MIN = 20 * 60
AGENT_INTERVAL_MAX = 40 * 60


def check_agent_commentary():
    global _last_agent_time
    now = time.time()
    if now - _last_agent_time > random.uniform(AGENT_INTERVAL_MIN, AGENT_INTERVAL_MAX):
        if has_listeners():
            log.info("[scheduler] random agent commentary")
            topic = segment_generator._pick_topic()
            executor.submit(_generate_and_queue, segment_generator.agent_take, topic)
        _last_agent_time = now


# --- Main ---

def main():
    log.info("=== drift-radio scheduler starting ===")
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
            check_agent_commentary()
            time.sleep(10)
    except KeyboardInterrupt:
        log.info("Shutting down...")
        stop_event.set()
        executor.shutdown(wait=False)


if __name__ == "__main__":
    main()
