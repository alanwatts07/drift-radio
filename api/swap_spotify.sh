#!/usr/bin/env bash
# ============================================================
#  FTR — Swap Spotify App Credentials
#  Run this when rate limited. Feed it new creds, it handles
#  the token flow and restarts the API.
#
#  Usage: ./swap_spotify.sh
# ============================================================

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

ENV_FILE="/home/morpheus/Hackstuff/drift-radio/api/.env"
API_DIR="/home/morpheus/Hackstuff/drift-radio/api"
VENV="/home/morpheus/Hackstuff/drift-radio/venv/bin/activate"
LOG_DIR="/home/morpheus/Hackstuff/drift-radio/logs"

echo -e "${CYAN}FTR — Spotify App Swap${NC}"
echo ""

# Get new credentials
read -p "New Client ID: " NEW_ID
read -p "New Client Secret: " NEW_SECRET

if [ -z "$NEW_ID" ] || [ -z "$NEW_SECRET" ]; then
    echo -e "${YELLOW}Both ID and Secret required. Aborting.${NC}"
    exit 1
fi

# Update .env — replace old creds, remove old refresh token
echo -e "\n${YELLOW}Updating .env...${NC}"
sed -i "s/^SPOTIFY_CLIENT_ID=.*/SPOTIFY_CLIENT_ID=$NEW_ID/" "$ENV_FILE"
sed -i "s/^SPOTIFY_CLIENT_SECRET=.*/SPOTIFY_CLIENT_SECRET=$NEW_SECRET/" "$ENV_FILE"
sed -i '/^SPOTIFY_REFRESH_TOKEN=/d' "$ENV_FILE"
echo -e "${GREEN}  ✓ Credentials updated${NC}"

# Run token flow
echo -e "\n${YELLOW}Getting new refresh token...${NC}"
source "$VENV"
cd "$API_DIR"
python get_spotify_token.py

# Restart API
echo -e "\n${YELLOW}Restarting API...${NC}"
pkill -f "uvicorn api:app" 2>/dev/null || true
sleep 2
cd "$API_DIR"
nohup uvicorn api:app --host 0.0.0.0 --port 8080 > "$LOG_DIR/api.log" 2>&1 &
disown
sleep 3

# Verify
RESPONSE=$(curl -s http://localhost:8080/nowplaying)
if echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('artist',''))" 2>/dev/null | grep -q .; then
    ARTIST=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('artist','?'))")
    TRACK=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('track','?'))")
    echo -e "\n${GREEN}✓ Back live! Now playing: $ARTIST — $TRACK${NC}"
else
    echo -e "\n${GREEN}✓ API restarted.${NC} Check https://radio.ftrai.uk"
fi
