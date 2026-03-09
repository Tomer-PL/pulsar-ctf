#!/bin/bash
# Launch Claude Code as the "claude" team player
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
GAME_SERVER="http://localhost:8888"

# Load Anthropic API key
export ANTHROPIC_API_KEY=$(grep ANTHROPIC_API_KEY /usr/local/workspace/neptune/.env | cut -d= -f2)

# Lock down the environment — blocks docker CLI, socket access, etc.
source "$SCRIPT_DIR/../restricted/setup_env.sh" claude

# Build the system prompt with team-specific values
PROMPT=$(cat "$SCRIPT_DIR/../system_prompt.md" \
    | sed "s|{{TEAM_NAME}}|CLAUDE (Anthropic Sonnet 4.6)|g" \
    | sed "s|{{TEAM_ID}}|claude|g" \
    | sed "s|{{GAME_SERVER}}|${GAME_SERVER}|g" \
    | sed "s|{{SOURCE_PATH}}|${ROOT_DIR}/challenges-source|g" \
    | sed "s|{{OWN_SERVICES}}|  - axis: localhost:14000\\n  - ico: localhost:14265\\n  - nilua: localhost:18080|g" \
    | sed "s|{{OPPONENT_SERVICES}}|GPT:\\n  - axis: localhost:24000\\n  - ico: localhost:24265\\n  - nilua: localhost:28080\\nGEMINI:\\n  - axis: localhost:34000\\n  - ico: localhost:34265\\n  - nilua: localhost:38080|g"
)

echo "=== Launching Claude Code for Team CLAUDE ==="
# Unset CLAUDECODE to allow nested launch
unset CLAUDECODE

claude --dangerously-skip-permissions --model claude-sonnet-4-6 -p "${PROMPT}"
