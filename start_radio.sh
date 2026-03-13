#!/usr/bin/env bash
# ============================================================
#  FTR — Fun Time Radio — Full Startup Script
#  Starts: API, UI, Engine (Docker), Cloudflare Tunnel
#  Usage:  ./start_radio.sh [--skip-engine] [--skip-tunnel]
# ============================================================

set -euo pipefail

RADIO_DIR="/home/morpheus/Hackstuff/drift-radio"
CLOUDFLARED_CONFIG="/home/morpheus/.cloudflared/config.yml"
LOG_DIR="$RADIO_DIR/logs"
mkdir -p "$LOG_DIR"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SKIP_ENGINE=false
SKIP_TUNNEL=false

for arg in "$@"; do
    case $arg in
        --skip-engine) SKIP_ENGINE=true ;;
        --skip-tunnel) SKIP_TUNNEL=true ;;
        --help|-h)
            echo "Usage: ./start_radio.sh [--skip-engine] [--skip-tunnel]"
            echo "  --skip-engine   Skip Docker (Icecast + Liquidsoap)"
            echo "  --skip-tunnel   Skip Cloudflare tunnel"
            exit 0
            ;;
    esac
done

cleanup() {
    echo -e "\n${YELLOW}Shutting down FTR...${NC}"
    # Kill backgrounded processes
    kill $API_PID 2>/dev/null && echo -e "${CYAN}  API stopped${NC}" || true
    kill $UI_PID 2>/dev/null && echo -e "${CYAN}  UI stopped${NC}" || true
    if [ "$SKIP_TUNNEL" = false ] && [ -n "${TUNNEL_PID:-}" ]; then
        kill $TUNNEL_PID 2>/dev/null && echo -e "${CYAN}  Tunnel stopped${NC}" || true
    fi
    if [ "$SKIP_ENGINE" = false ]; then
        cd "$RADIO_DIR/engine" && docker compose down 2>/dev/null && echo -e "${CYAN}  Engine stopped${NC}" || true
    fi
    echo -e "${GREEN}FTR shut down cleanly.${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  FTR — Fun Time Radio — Starting Up${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# ----------------------------------------------------------
# 1. Check prerequisites
# ----------------------------------------------------------
echo -e "${YELLOW}[1/5] Checking prerequisites...${NC}"

if [ ! -d "$RADIO_DIR/venv" ]; then
    echo -e "${RED}  Python venv not found. Creating...${NC}"
    python3 -m venv "$RADIO_DIR/venv"
    source "$RADIO_DIR/venv/bin/activate"
    pip install -r "$RADIO_DIR/api/requirements.txt" -q
    pip install -r "$RADIO_DIR/engine/requirements.txt" -q
else
    source "$RADIO_DIR/venv/bin/activate"
fi
echo -e "${GREEN}  ✓ Python venv activated${NC}"

if [ ! -d "$RADIO_DIR/ui/node_modules" ]; then
    echo -e "${RED}  node_modules not found. Installing...${NC}"
    cd "$RADIO_DIR/ui" && npm install
fi
echo -e "${GREEN}  ✓ Node modules ready${NC}"

if [ ! -f "$RADIO_DIR/api/.env" ]; then
    echo -e "${YELLOW}  ⚠ No .env in api/ — copying from .env.example${NC}"
    echo -e "${YELLOW}    Fill in your Spotify credentials!${NC}"
    cp "$RADIO_DIR/api/.env.example" "$RADIO_DIR/api/.env"
fi
echo -e "${GREEN}  ✓ .env exists${NC}"

# ----------------------------------------------------------
# 2. Start Engine (Icecast + Liquidsoap)
# ----------------------------------------------------------
if [ "$SKIP_ENGINE" = false ]; then
    echo -e "\n${YELLOW}[2/5] Starting Engine (Icecast + Liquidsoap)...${NC}"
    if ! docker info >/dev/null 2>&1; then
        echo -e "${RED}  ✗ Docker not running!${NC}"
        echo -e "${RED}    Open Docker Desktop and enable WSL integration, then retry.${NC}"
        echo -e "${YELLOW}    Continuing without engine...${NC}"
        SKIP_ENGINE=true
    else
        cd "$RADIO_DIR/engine"
        docker compose up -d 2>&1 | tail -5
        echo -e "${GREEN}  ✓ Icecast on :8000 | Liquidsoap on :8005 / :1234${NC}"
    fi
else
    echo -e "\n${YELLOW}[2/5] Skipping Engine (--skip-engine)${NC}"
fi

# ----------------------------------------------------------
# 3. Start API (FastAPI)
# ----------------------------------------------------------
echo -e "\n${YELLOW}[3/5] Starting API (FastAPI)...${NC}"
cd "$RADIO_DIR/api"
uvicorn api:app --host 0.0.0.0 --port 8080 > "$LOG_DIR/api.log" 2>&1 &
API_PID=$!
sleep 1
if kill -0 $API_PID 2>/dev/null; then
    echo -e "${GREEN}  ✓ API running on :8080 (PID $API_PID)${NC}"
else
    echo -e "${RED}  ✗ API failed to start — check $LOG_DIR/api.log${NC}"
fi

# ----------------------------------------------------------
# 4. Start UI (Next.js)
# ----------------------------------------------------------
echo -e "\n${YELLOW}[4/5] Starting UI (Next.js)...${NC}"
cd "$RADIO_DIR/ui"
npm run dev > "$LOG_DIR/ui.log" 2>&1 &
UI_PID=$!
sleep 2
if kill -0 $UI_PID 2>/dev/null; then
    echo -e "${GREEN}  ✓ UI running on :3000 (PID $UI_PID)${NC}"
else
    echo -e "${RED}  ✗ UI failed to start — check $LOG_DIR/ui.log${NC}"
fi

# ----------------------------------------------------------
# 5. Start Cloudflare Tunnel
# ----------------------------------------------------------
if [ "$SKIP_TUNNEL" = false ]; then
    echo -e "\n${YELLOW}[5/5] Starting Cloudflare Tunnel...${NC}"
    if ! command -v cloudflared &>/dev/null; then
        echo -e "${RED}  ✗ cloudflared not installed${NC}"
        SKIP_TUNNEL=true
    else
        cloudflared tunnel run > "$LOG_DIR/tunnel.log" 2>&1 &
        TUNNEL_PID=$!
        sleep 3
        if kill -0 $TUNNEL_PID 2>/dev/null; then
            echo -e "${GREEN}  ✓ Tunnel running (PID $TUNNEL_PID)${NC}"
        else
            echo -e "${RED}  ✗ Tunnel failed — check $LOG_DIR/tunnel.log${NC}"
        fi
    fi
else
    echo -e "\n${YELLOW}[5/5] Skipping Tunnel (--skip-tunnel)${NC}"
fi

# ----------------------------------------------------------
# Summary
# ----------------------------------------------------------
echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  FTR is live!${NC}"
echo -e "${CYAN}========================================${NC}"
echo -e "  ${GREEN}UI:${NC}      http://localhost:3000"
echo -e "  ${GREEN}API:${NC}     http://localhost:8080"
echo -e "  ${GREEN}Icecast:${NC} http://localhost:8000"
echo -e "  ${GREEN}Public:${NC}  https://radio.ftrai.uk"
echo ""
echo -e "${YELLOW}  Don't forget to run on Windows:${NC}"
echo -e "  ${CYAN}ffmpeg -f dshow -i audio=\"Voicemeeter Out B1 (VB-Audio Voicemeeter VAIO)\" -ac 2 -ar 44100 -acodec libmp3lame -b:a 192k -f mp3 icecast://source:hackme@localhost:8005/spotify${NC}"
echo ""
echo -e "${YELLOW}  Logs:${NC} $LOG_DIR/"
echo -e "${YELLOW}  Press Ctrl+C to stop everything${NC}"
echo ""

# Wait for all background processes
wait
