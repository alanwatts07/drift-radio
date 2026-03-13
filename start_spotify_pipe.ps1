# FTR — Spotify Audio Pipe
# Routes Spotify audio from VoiceMeeter into Liquidsoap/Icecast
# Run this in PowerShell on the Windows side

Write-Host "FTR — Starting Spotify audio pipe..." -ForegroundColor Cyan
Write-Host "Make sure VoiceMeeter is running and Spotify is routed through it." -ForegroundColor Yellow
Write-Host ""

ffmpeg -f dshow -i audio="Voicemeeter Out B1 (VB-Audio Voicemeeter VAIO)" -ac 2 -ar 44100 -acodec libmp3lame -b:a 192k -f mp3 icecast://source:hackme@localhost:8005/spotify
