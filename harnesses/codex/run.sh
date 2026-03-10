#!/bin/bash
# Launch OpenAI Codex CLI as the "gpt" team player
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
GAME_SERVER="${GAME_SERVER:-http://localhost:8888}"

# Lock down the environment — blocks docker CLI, socket access, etc.
source "$SCRIPT_DIR/../restricted/setup_env.sh" gpt 2>/dev/null || true

# Build the system prompt with team-specific values
PROMPT=$(cat "$SCRIPT_DIR/../system_prompt.md" \
    | sed "s|{{TEAM_NAME}}|GPT (OpenAI GPT-5.3 Codex)|g" \
    | sed "s|{{TEAM_ID}}|gpt|g" \
    | sed "s|{{GAME_SERVER}}|${GAME_SERVER}|g" \
    | sed "s|{{SOURCE_PATH}}|${ROOT_DIR}/challenges-source|g" \
    | sed "s|{{PATCH_PATH}}|${ROOT_DIR}/challenges-source|g" \
    | sed "s|{{OWN_SERVICES}}|  - axis: localhost:24000\\n  - ico: localhost:24265\\n  - nilua: localhost:28080|g" \
    | sed "s|{{OPPONENT_SERVICES}}|CLAUDE:\\n  - axis: localhost:14000\\n  - ico: localhost:14265\\n  - nilua: localhost:18080|g"
)

echo "=== Launching Codex CLI for Team GPT ==="
# --dangerously-bypass-approvals-and-sandbox needed for network access to services
# Our restricted env already blocks docker CLI/socket, so this is safe
codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check --model gpt-5.3-codex "${PROMPT}"
