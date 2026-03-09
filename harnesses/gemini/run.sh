#!/bin/bash
# Launch Gemini CLI as the "gemini" team player
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
GAME_SERVER="http://localhost:8888"

# Gemini CLI needs Node 20+
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"
nvm use 22 --silent 2>/dev/null || true

# Lock down the environment — blocks docker CLI, socket access, etc.
source "$SCRIPT_DIR/../restricted/setup_env.sh" gemini

# Build the system prompt with team-specific values
PROMPT=$(cat "$SCRIPT_DIR/../system_prompt.md" \
    | sed "s|{{TEAM_NAME}}|GEMINI (Google Gemini 2.5 Pro)|g" \
    | sed "s|{{TEAM_ID}}|gemini|g" \
    | sed "s|{{GAME_SERVER}}|${GAME_SERVER}|g" \
    | sed "s|{{SOURCE_PATH}}|${ROOT_DIR}/challenges-source|g" \
    | sed "s|{{OWN_SERVICES}}|  - axis: localhost:34000\\n  - ico: localhost:34265\\n  - nilua: localhost:38080|g" \
    | sed "s|{{OPPONENT_SERVICES}}|CLAUDE:\\n  - axis: localhost:14000\\n  - ico: localhost:14265\\n  - nilua: localhost:18080\\nGPT:\\n  - axis: localhost:24000\\n  - ico: localhost:24265\\n  - nilua: localhost:28080|g"
)

echo "=== Launching Gemini CLI for Team GEMINI ==="
gemini --yolo --sandbox=false -m gemini-2.5-pro -p "${PROMPT}"
