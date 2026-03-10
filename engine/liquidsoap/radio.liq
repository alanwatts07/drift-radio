#!/usr/bin/liquidsoap

# drift-radio — Liquidsoap radio engine
# Priority: injected segments > Spotify (BUTT) > local playlist

settings.server.telnet.set(true)
settings.server.telnet.port.set(1234)
settings.server.telnet.bind_addr.set("0.0.0.0")

# --- Sources ---

# Injected segments (Python drops files here via telnet)
segments = request.queue(id="segments")

# Spotify passthrough via BUTT → harbor input
spotify = input.harbor(
  "spotify",
  port=8005
)

# Local music fallback
local = playlist(
  "/music/",
  reload=3600,
  mode="randomize"
)

# --- Fallback chain ---
# Segments take priority, then Spotify, then local music
radio = fallback(
  track_sensitive=true,
  [
    segments,
    spotify,
    local
  ]
)

# Make infallible (silence if all sources empty)
radio = mksafe(radio)

# --- Output to Icecast ---
output.icecast(
  %mp3(bitrate=192),
  host="icecast",
  port=8000,
  password="hackme",
  mount="/live.mp3",
  name="drift-radio",
  description="AI Radio Station",
  radio
)
