#!/usr/bin/env python3
"""Mix speech over a music bed using pydub."""

import random
from pathlib import Path
from pydub import AudioSegment
import config


def mix_over_bed(speech_path: str | Path, output_path: str | Path, bed_volume_db: float = -18.0) -> Path:
    """
    Mix speech MP3 over a random music bed.
    Music bed is ducked to bed_volume_db and trimmed to match speech length.
    Returns path to mixed output.
    """
    speech_path = Path(speech_path)
    output_path = Path(output_path)

    speech = AudioSegment.from_mp3(speech_path)
    beds = list(Path(config.MUSIC_BEDS_DIR).glob("*.mp3"))

    if not beds:
        # No beds available — return speech unchanged
        speech.export(str(output_path), format="mp3", bitrate="192k")
        return output_path

    bed_file = random.choice(beds)
    bed = AudioSegment.from_mp3(bed_file)

    # Loop bed if shorter than speech
    while len(bed) < len(speech):
        bed = bed + bed

    # Trim bed to speech length
    bed = bed[: len(speech)]

    # Duck the bed
    bed = bed + bed_volume_db

    # Overlay speech on bed
    mixed = bed.overlay(speech)
    mixed.export(str(output_path), format="mp3", bitrate="192k")
    return output_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: audio_mixer.py <speech.mp3> <output.mp3>")
        sys.exit(1)

    result = mix_over_bed(sys.argv[1], sys.argv[2])
    print(f"Mixed → {result}")
