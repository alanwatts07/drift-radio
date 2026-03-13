#!/usr/bin/env python3
"""
One-time Spotify OAuth — gets a refresh token for FTR.
Run this, open the URL it prints, authorize, paste the redirect URL back.
"""
import os
from dotenv import load_dotenv
load_dotenv()

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"

import urllib.parse
auth_url = (
    "https://accounts.spotify.com/authorize?"
    + urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    })
)

print("\n1. Open this URL in your browser:\n")
print(auth_url)
print("\n2. Authorize the app. You'll be redirected to a URL like:")
print("   http://127.0.0.1:8888/callback?code=AQAB...")
print("\n3. Paste the FULL redirect URL below:\n")

redirect_response = input("Paste URL: ").strip()

# Extract the code
code = urllib.parse.parse_qs(urllib.parse.urlparse(redirect_response).query)["code"][0]

# Exchange code for tokens
import requests
resp = requests.post("https://accounts.spotify.com/api/token", data={
    "grant_type": "authorization_code",
    "code": code,
    "redirect_uri": REDIRECT_URI,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
})
resp.raise_for_status()
tokens = resp.json()

refresh_token = tokens["refresh_token"]
print(f"\n✓ Got refresh token!\n")
print(f"SPOTIFY_REFRESH_TOKEN={refresh_token}")

# Append to .env
env_path = os.path.join(os.path.dirname(__file__), ".env")
with open(env_path, "a") as f:
    f.write(f"\nSPOTIFY_REFRESH_TOKEN={refresh_token}\n")
print(f"\n✓ Saved to {env_path}")
print("  Restart the API and you're good!")
