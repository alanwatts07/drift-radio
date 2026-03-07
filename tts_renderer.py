#!/usr/bin/env python3
"""OpenAI TTS renderer — converts script text to MP3 using onyx voice."""

import sys
import os
from pathlib import Path
from openai import OpenAI
import config

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def render(text: str, output_path: str | Path) -> Path:
    """Render text to speech, save as MP3. Returns output path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    response = client.audio.speech.create(
        model="tts-1",
        voice=config.TTS_VOICE,
        input=text,
        speed=config.TTS_SPEED,
    )
    response.stream_to_file(str(output_path))
    print(f"[tts] rendered → {output_path}")
    return output_path


if __name__ == "__main__":
    # Quick test: python tts_renderer.py "Hello, this is drift radio."
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Drift radio. On air."
    out = Path(config.SEGMENTS_DIR) / "test_tts.mp3"
    render(text, out)
    print(f"Saved to {out}")
