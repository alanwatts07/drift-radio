import os
from dotenv import load_dotenv

load_dotenv()

# Drift agents
AGENTS = ["max", "beth", "gerald"]
DRIFT_AGENTS_API_URL = os.getenv("DRIFT_AGENTS_API_URL", "https://agents-api.mattcorwin.dev")

# Paths
SEGMENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "segments")
MUSIC_BEDS_DIR = "music_beds/"
MUSIC_DIR = "music/"
LOGS_DIR = "logs/"

# Liquidsoap telnet
LIQUIDSOAP_TELNET = ("localhost", 1234)

# Icecast
ICECAST_STATUS_URL = os.getenv("ICECAST_STATUS_URL", "http://localhost:8000/status-json.xsl")
ICECAST_PASSWORD = os.getenv("ICECAST_PASSWORD", "hackme")

# TTS
TTS_VOICE = "onyx"
TTS_SPEED = 0.95

# Schedule (minute-of-hour triggers)
SCHEDULE = {
    "news_break_minute": 30,
    "full_broadcast_minute": 0,
}

# Claude CLI
CLAUDE_MAX_TURNS_NEWS = 3
CLAUDE_MAX_TURNS_FACT = 1
CLAUDE_TIMEOUT = 120

# Spotify polling interval (seconds) — keep high to avoid rate limits
SPOTIFY_POLL_INTERVAL = 15

# Segment cleanup: keep last N segments
SEGMENTS_KEEP = 20
