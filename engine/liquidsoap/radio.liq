#!/usr/bin/liquidsoap

# drift-radio — Liquidsoap radio engine
# Priority: injected segments > Spotify (BUTT) > local playlist

settings.server.telnet.set(true)
settings.server.telnet.port.set(1234)
settings.server.telnet.bind_addr.set("0.0.0.0")

# --- Sources ---

# Urgent announcements — interrupts immediately
urgent = request.queue(id="urgent")

# Injected segments (waits for current track to end)
segments = request.queue(id="segments")

# Spotify passthrough via BUTT → harbor input
spotify = input.harbor(
  "spotify",
  port=8005,
  buffer=1.0
)
spotify = buffer(buffer=0.5, max=10.0, spotify)

# Local music fallback
local = playlist(
  "/music/",
  reload=3600,
  mode="randomize"
)

# --- Fallback chain ---
# Spotify takes over local immediately when connected (track_sensitive=false)
music = fallback(
  track_sensitive=false,
  [
    spotify,
    local
  ]
)

# Segments wait for current track to end
radio = fallback(
  track_sensitive=true,
  [
    segments,
    music
  ]
)

# Urgent cuts in immediately over everything
radio = fallback(
  track_sensitive=false,
  transition_length=2.0,
  [
    urgent,
    radio
  ]
)

# Make infallible (silence if all sources empty)
radio = mksafe(radio)

# --- Output to Icecast ---
output.icecast(
  %mp3(bitrate=128),
  host="icecast",
  port=8000,
  password="hackme",
  mount="/live.mp3",
  name="drift-radio",
  description="AI Radio Station",
  radio
)
