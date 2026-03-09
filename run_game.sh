#!/bin/bash
# Master launch script for the LLM Attack-Defense CTF
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "============================================"
echo "  AttDef - LLM Attack-Defense CTF"
echo "  Claude Sonnet 4.6 vs GPT-5.3 Codex vs Gemini 3.1 Pro"
echo "============================================"
echo ""

# Step 1: Build all service containers
echo "[1/4] Building service containers..."
docker compose -f "$ROOT_DIR/docker-compose.yml" build 2>&1 | tee "$LOG_DIR/build.log"

# Step 2: Plant initial flags so services can start (nilua requires /flag)
echo "[2/4] Starting services and game server..."
docker compose -f "$ROOT_DIR/docker-compose.yml" up -d 2>&1 | tee "$LOG_DIR/startup.log"

# Wait for services to be healthy
echo "Waiting for services to start..."
sleep 10

# Verify all containers are running
EXPECTED=10  # 9 services + 1 game server
RUNNING=$(docker compose -f "$ROOT_DIR/docker-compose.yml" ps --status running -q | wc -l | tr -d ' ')
echo "Running containers: $RUNNING / $EXPECTED"

if [ "$RUNNING" -lt "$EXPECTED" ]; then
    echo "WARNING: Not all containers are running:"
    docker compose -f "$ROOT_DIR/docker-compose.yml" ps
    echo ""
    echo "Continue anyway? (y/n)"
    read -r answer
    if [ "$answer" != "y" ]; then
        echo "Aborting."
        docker compose -f "$ROOT_DIR/docker-compose.yml" down
        exit 1
    fi
fi

echo ""
echo "[3/4] Services are up!"
echo ""
echo "  Port Mappings:"
echo "  ┌──────────┬──────────────────┬──────────────────┬──────────────────┐"
echo "  │ Service  │ Claude           │ GPT              │ Gemini           │"
echo "  ├──────────┼──────────────────┼──────────────────┼──────────────────┤"
echo "  │ axis     │ localhost:14000  │ localhost:24000   │ localhost:34000  │"
echo "  │ ico      │ localhost:14265  │ localhost:24265   │ localhost:34265  │"
echo "  │ nilua    │ localhost:18080  │ localhost:28080   │ localhost:38080  │"
echo "  └──────────┴──────────────────┴──────────────────┴──────────────────┘"
echo ""
echo "  Scoreboard:  http://localhost:8888/"
echo "  API docs:    http://localhost:8888/docs"
echo "  Game log:    tail -f $LOG_DIR/game_events.log"
echo ""

# Step 4: Launch LLM agents
echo "[4/4] Launch LLM agents:"
echo ""
echo "  Option A — each in a separate terminal:"
echo "    Terminal 1:  bash $ROOT_DIR/harnesses/claude/run.sh"
echo "    Terminal 2:  bash $ROOT_DIR/harnesses/codex/run.sh"
echo "    Terminal 3:  bash $ROOT_DIR/harnesses/gemini/run.sh"
echo ""
echo "  Option B — all at once (backgrounded with logging):"
echo "    bash $ROOT_DIR/launch_agents.sh"
echo ""
echo "============================================"
echo "  Game is LIVE! Scoreboard: http://localhost:8888/"
echo "============================================"
