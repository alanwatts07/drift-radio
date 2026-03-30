#!/usr/bin/env python3
"""Content generation — Claude CLI + drift agents API → TTS → MP3 segment."""

import subprocess
import random
import re
import logging
import os
import requests
from pathlib import Path
from datetime import datetime

import config
import tts_renderer

log = logging.getLogger(__name__)

# Mood tag pattern: [MOOD: excited] at the start of a script
_MOOD_RE = re.compile(r"^\s*\[MOOD:\s*(\w+)\]\s*", re.IGNORECASE)

MOOD_INSTRUCTION = (
    "Start your response with a mood tag like [MOOD: excited] or [MOOD: somber]. "
    "Valid moods: excited, fired_up, amused, curious, neutral, serious, concerned, "
    "somber, reflective, suspicious, unhinged. Pick the one that matches your vibe."
)


def _parse_mood(script: str) -> tuple[str, str]:
    """Extract mood tag from script. Returns (mood, clean_script)."""
    m = _MOOD_RE.match(script)
    if m:
        mood = m.group(1).lower()
        clean = script[m.end():]
        if mood in config.MOOD_SPEEDS:
            return mood, clean
        log.warning(f"[gen] unknown mood '{mood}', defaulting to neutral")
    return "neutral", script


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


def news_roundtable(headlines: list[str], tech_story: str, ethics_story: str, psych_story: str) -> Path:
    """Generate a multi-voice news broadcast:
    1. Max gives a tech take
    2. Beth gives an ethics take
    3. Private Aye gives a psychology/profiling take
    4. Terence (anchor) wraps up with headlines and sends it back to music
    All stitched into one MP3, each with their own TTS voice.
    """
    from pydub import AudioSegment

    log.info("[gen] news roundtable starting")
    parts: list[Path] = []

    # 0. Terence intro — opens the news segment
    headline_text = "\n".join(f"- {h}" for h in headlines)
    intro_prompt = (
        "You are Terence, the anchor for FTR — Fun Time Radio. You're opening "
        "the news roundtable. Introduce the segment briefly — something like "
        "'This is FTR news, here's what's happening' — then tease the headlines. "
        "Dry, deadpan, no hype. Keep it under 15 seconds. "
        "Output only the spoken script.\n\n"
        f"Headlines:\n{headline_text}"
    )
    try:
        intro_script = _claude(intro_prompt, max_turns=1)
        intro_path = _segment_path("roundtable_intro")
        tts_renderer.render(intro_script, intro_path, voice=config.AGENT_VOICES["anchor"])
        parts.append(intro_path)
        log.info("[gen] terence intro done")
    except Exception as e:
        log.error(f"[gen] terence intro failed: {e}")

    # 1. Agent segments — each gets their story, their voice
    agent_assignments = [
        ("max", tech_story, "tech"),
        ("beth", ethics_story, "ethics"),
        ("private_aye", psych_story, "psychology and human behavior"),
    ]

    for agent_name, story, domain in agent_assignments:
        if not story or not story.strip():
            log.warning(f"[gen] no {domain} story for {agent_name}, skipping")
            continue

        mood_prompt = f" {MOOD_INSTRUCTION}"
        try:
            resp = requests.post(
                f"{config.DRIFT_AGENTS_API_URL}/chat",
                json={
                    "agent": agent_name,
                    "message": (
                        f"Here's a news story about {domain}. Give your take on it as a "
                        f"45-second radio segment. Stay in character, be opinionated, "
                        f"no fluff.{mood_prompt}\n\nStory: {story}"
                    ),
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            script = data.get("response") or data.get("message") or str(data)
        except Exception as e:
            log.warning(f"[gen] drift agents API failed for {agent_name} ({e}), falling back to Claude")
            prompt = (
                f"You are a radio personality named {agent_name}. Your specialty is {domain}. "
                f"Give your take on this story as a 45-second radio segment. "
                f"Be opinionated, dry tone, no filler.{mood_prompt} "
                f"Output only the mood tag + script.\n\nStory: {story}"
            )
            script = _claude(prompt, max_turns=1)

        mood, clean_script = _parse_mood(script)
        speed = config.MOOD_SPEEDS[mood]
        voice = config.AGENT_VOICES.get(agent_name, config.TTS_VOICE)
        seg_path = _segment_path(f"roundtable_{agent_name}")
        tts_renderer.render(clean_script, seg_path, voice=voice, speed=speed)
        parts.append(seg_path)
        log.info(f"[gen] {agent_name} segment done (voice: {voice}, mood: {mood}, speed: {speed})")

    # Terence wraps up with headlines and sends it back to music
    headline_text = "\n".join(f"- {h}" for h in headlines)
    anchor_prompt = (
        f"You are Terence, the anchor for FTR — Fun Time Radio. You're wrapping up "
        f"the news roundtable. Recap these headlines briefly, then sign off and send "
        f"it back to the music. Dry, deadpan style. Keep it under 30 seconds. "
        f"No filler, no hype. Output only the spoken script.\n\n"
        f"Headlines:\n{headline_text}"
    )
    try:
        anchor_script = _claude(anchor_prompt, max_turns=1)
        anchor_path = _segment_path("roundtable_terence")
        tts_renderer.render(anchor_script, anchor_path, voice=config.AGENT_VOICES["anchor"])
        parts.append(anchor_path)
        log.info("[gen] terence wrap-up done")
    except Exception as e:
        log.error(f"[gen] terence wrap-up failed: {e}")

    if not parts:
        raise RuntimeError("No segments were generated for roundtable")

    # Stitch all parts into one broadcast MP3
    combined = AudioSegment.empty()
    pause = AudioSegment.silent(duration=800)  # 0.8s pause between segments

    for i, part in enumerate(parts):
        seg = AudioSegment.from_mp3(str(part))
        if i > 0:
            combined += pause
        combined += seg

    output = _segment_path("news_roundtable")
    combined.export(str(output), format="mp3", bitrate="192k")
    log.info(f"[gen] news roundtable complete: {output} ({len(combined) / 1000:.1f}s)")

    # Clean up individual parts
    for part in parts:
        part.unlink(missing_ok=True)

    return output


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
