#!/usr/bin/env python3
"""OpenAI TTS renderer — converts script text to MP3 using onyx voice."""

import sys
import os
import subprocess
from pathlib import Path
from openai import OpenAI
import config

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def render(text: str, output_path: str | Path, voice: str = None, speed: float = None) -> Path:
    """Render text to speech, save as MP3. Returns output path.
    voice: OpenAI voice ID override (default: config.TTS_VOICE).
    speed: TTS speed override (default: config.TTS_SPEED)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    response = client.audio.speech.create(
        model="tts-1",
        voice=voice or config.TTS_VOICE,
        input=text,
        speed=speed or config.TTS_SPEED,
    )
    tmp_path = output_path.with_suffix(".mono.mp3")
    response.stream_to_file(str(tmp_path))

    # Convert mono → stereo, normalize loudness to broadcast level (-14 LUFS)
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(tmp_path),
            "-ac", "2",
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-b:a", "192k",
            str(output_path),
        ],
        check=True, capture_output=True,
    )
    tmp_path.unlink(missing_ok=True)

    print(f"[tts] rendered → {output_path}")
    return output_path


if __name__ == "__main__":
    # Quick test: python tts_renderer.py "Hello, this is drift radio."
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Drift radio. On air."
    out = Path(config.SEGMENTS_DIR) / "test_tts.mp3"
    render(text, out)
    print(f"Saved to {out}")
