#!/usr/bin/env python3
"""Content generation — Claude CLI + drift agents API → TTS → MP3 segment."""

import subprocess
import random
import logging
import os
import requests
from pathlib import Path
from datetime import datetime

import config
import tts_renderer

log = logging.getLogger(__name__)


def _claude(prompt: str, system: str = None, max_turns: int = 1, use_web: bool = False, timeout: int = config.CLAUDE_TIMEOUT) -> str:
    """Run Claude CLI, return stdout."""
    cmd = ["claude", "-p", prompt, "--max-turns", str(max_turns)]
    if use_web:
        cmd += ["--allowedTools", "WebSearch,WebFetch"]
    if system:
        cmd += ["--system-prompt", system]
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        log.error(f"Claude CLI error: {result.stderr[:500]}")
        raise RuntimeError(f"Claude exited {result.returncode}")
    text = result.stdout.strip()
    # Catch Claude meta-output that shouldn't be TTS'd
    error_markers = ["max turns", "reached max", "error", "I cannot", "I can't"]
    if any(marker in text.lower() for marker in error_markers) and len(text) < 200:
        log.warning(f"[gen] Claude returned meta/error text, not a script: {text[:200]}")
        raise RuntimeError(f"Claude returned error text: {text[:100]}")
    return text


def _segment_path(label: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(config.SEGMENTS_DIR) / f"{label}_{ts}.mp3"


def song_fact(artist: str, track: str) -> Path:
    """Generate a ~40s song fact segment."""
    prompt = (
        f"You are a dry, deadpan radio host for FTR — Fun Time Radio. Write a 40-second radio script "
        f"with 3 interesting facts about '{artist} - {track}'. "
        f"Dry tone, no enthusiasm, no filler phrases like 'stay tuned' or 'up next'. "
        f"Just facts delivered with flat wit. Output only the script, nothing else."
    )
    log.info(f"[gen] song fact: {artist} - {track}")
    script = _claude(prompt, max_turns=config.CLAUDE_MAX_TURNS_FACT)
    out = _segment_path("song_fact")
    return tts_renderer.render(script, out)


def news_break() -> Path:
    """Generate a ~60s news break using web search."""
    prompt = (
        "You are a dry, deadpan radio host for FTR — Fun Time Radio. Use web search to find 3 real, "
        "interesting news stories from today. Write a 60-second radio script. "
        "No filler, no hype. Just facts with dry wit. "
        "You may mention source names naturally (e.g. 'according to Reuters') but NEVER include URLs or links. "
        "Output only the spoken script, nothing else."
    )
    log.info("[gen] news break")
    script = _claude(prompt, max_turns=config.CLAUDE_MAX_TURNS_NEWS, use_web=True)
    out = _segment_path("news_break")
    return tts_renderer.render(script, out)


def agent_take(topic: str, agent: str | None = None) -> Path:
    """Get a ~45s take from a drift agent on a topic."""
    if agent is None:
        agent = random.choice(config.AGENTS)
    log.info(f"[gen] agent take: {agent} on '{topic}'")

    try:
        resp = requests.post(
            f"{config.DRIFT_AGENTS_API_URL}/chat",
            json={
                "agent": agent,
                "message": (
                    f"Give me your take on {topic} as a 45-second radio segment. "
                    f"Stay in character, dry tone, no fluff."
                ),
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        script = data.get("response") or data.get("message") or str(data)
    except Exception as e:
        log.warning(f"[gen] drift agents API failed ({e}), falling back to Claude")
        prompt = (
            f"You are a radio personality named {agent}. "
            f"Give your take on '{topic}' as a 45-second radio segment. "
            f"Dry, opinionated, no filler. Output only the script."
        )
        script = _claude(prompt, max_turns=1)

    out = _segment_path(f"agent_{agent}")
    return tts_renderer.render(script, out)


def full_broadcast(topic: str | None = None) -> list[Path]:
    """Generate a ~3-4 min full broadcast: news + agent takes."""
    log.info("[gen] full broadcast")
    segments = []

    # News segment
    try:
        segments.append(news_break())
    except Exception as e:
        log.error(f"[gen] news break failed: {e}")

    # Agent takes (pick 2-3 agents)
    agents = random.sample(config.AGENTS, k=min(2, len(config.AGENTS)))
    topic = topic or _pick_topic()
    for agent in agents:
        try:
            segments.append(agent_take(topic, agent))
        except Exception as e:
            log.error(f"[gen] agent take failed ({agent}): {e}")

    return segments


def _pick_topic() -> str:
    """Pick a random discussion topic."""
    topics = [
        "the current state of AI",
        "why everyone is exhausted",
        "the attention economy",
        "late-stage capitalism",
        "whether the internet was a mistake",
        "what counts as music anymore",
        "the death of expertise",
        "parasocial relationships",
    ]
    return random.choice(topics)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    mode = sys.argv[1] if len(sys.argv) > 1 else "news"
    if mode == "news":
        p = news_break()
    elif mode == "song":
        artist = sys.argv[2] if len(sys.argv) > 2 else "Radiohead"
        track = sys.argv[3] if len(sys.argv) > 3 else "Karma Police"
        p = song_fact(artist, track)
    elif mode == "agent":
        topic = sys.argv[2] if len(sys.argv) > 2 else "the state of things"
        p = agent_take(topic)
    elif mode == "broadcast":
        paths = full_broadcast()
        print(f"Generated {len(paths)} segments")
        sys.exit(0)
    else:
        print("Usage: segment_generator.py [news|song ARTIST TRACK|agent TOPIC|broadcast]")
        sys.exit(1)
    print(f"Segment: {p}")
