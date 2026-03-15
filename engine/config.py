import os
from dotenv import load_dotenv

load_dotenv()

# Drift agents
AGENTS = ["max", "beth", "private_aye"]
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
TTS_VOICE = "shimmer"
TTS_SPEED = 0.95

# Per-agent TTS voices (OpenAI voice IDs)
AGENT_VOICES = {
    "anchor": "onyx",      # neutral headlines anchor
    "max": "echo",          # Max — tech takes
    "beth": "nova",         # Beth — ethics / moral compass
    "private_aye": "fable",  # Private Aye (Earl Von Schnuff) — psychology / profiling
}

# Mood → TTS speed mapping
MOOD_SPEEDS = {
    "excited":     1.10,
    "fired_up":    1.12,
    "amused":      1.05,
    "curious":     1.00,
    "neutral":     0.95,
    "serious":     0.90,
    "concerned":   0.88,
    "somber":      0.85,
    "reflective":  0.88,
    "suspicious":  0.92,
    "unhinged":    1.15,
}

# Schedule (minute-of-hour triggers)
SCHEDULE = {
    "news_break_minute": 30,
    "full_broadcast_minute": 0,
}

# Claude CLI
CLAUDE_MAX_TURNS_NEWS = 6
CLAUDE_MAX_TURNS_FACT = 1
CLAUDE_TIMEOUT = 120

# Spotify polling interval (seconds) — keep high to avoid rate limits
SPOTIFY_POLL_INTERVAL = 15

# Segment cleanup: keep last N segments
SEGMENTS_KEEP = 20

# n8n webhook for news roundtable (triggers RSS → agents → broadcast)
N8N_NEWS_WEBHOOK = os.getenv("N8N_NEWS_WEBHOOK", "http://localhost:5678/webhook/68744254-16c0-4754-a349-0964f70461a1")
