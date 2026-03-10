#!/bin/bash
# Container entrypoint for LLM agents.
# Renders the system prompt with Docker network addresses, then launches the agent.
set -euo pipefail

TEAM_ID="${TEAM_ID:?TEAM_ID environment variable required}"
GAME_SERVER="${GAME_SERVER:-http://game-server:8888}"
SOURCE_PATH="${SOURCE_PATH:-/app/challenges-source}"
PATCH_PATH="${PATCH_PATH:-/patches}"

# Service addresses use Docker DNS names with internal ports
case "$TEAM_ID" in
  claude)
    TEAM_NAME="CLAUDE (Anthropic Sonnet 4.6)"
    OWN="  - axis: claude-axis:4000\n  - ico: claude-ico:4265\n  - nilua: claude-nilua:8080"
    OPP="GPT:\n  - axis: gpt-axis:4000\n  - ico: gpt-ico:4265\n  - nilua: gpt-nilua:8080"
    ;;
  gpt)
    TEAM_NAME="GPT (OpenAI GPT-5.3 Codex)"
    OWN="  - axis: gpt-axis:4000\n  - ico: gpt-ico:4265\n  - nilua: gpt-nilua:8080"
    OPP="CLAUDE:\n  - axis: claude-axis:4000\n  - ico: claude-ico:4265\n  - nilua: claude-nilua:8080"
    ;;
  *)
    echo "ERROR: Unknown TEAM_ID: $TEAM_ID (expected: claude, gpt)"
    exit 1
    ;;
esac

# Render the system prompt template
TEMPLATE="/app/harnesses/system_prompt.md"
RENDERED=$(sed \
  -e "s|{{TEAM_NAME}}|${TEAM_NAME}|g" \
  -e "s|{{TEAM_ID}}|${TEAM_ID}|g" \
  -e "s|{{GAME_SERVER}}|${GAME_SERVER}|g" \
  -e "s|{{SOURCE_PATH}}|${SOURCE_PATH}|g" \
  -e "s|{{PATCH_PATH}}|${PATCH_PATH}|g" \
  -e "s|{{OWN_SERVICES}}|${OWN}|g" \
  -e "s|{{OPPONENT_SERVICES}}|${OPP}|g" \
  "$TEMPLATE")

# Write rendered prompt where agent.py and run_loop.sh expect it
mkdir -p /app/harnesses/claude /app/harnesses/"${TEAM_ID}"
echo "$RENDERED" > /app/harnesses/claude/prompt_rendered.txt
echo "$RENDERED" > /app/harnesses/"${TEAM_ID}"/prompt_rendered.txt

echo "=== Agent Container: ${TEAM_NAME} ==="
echo "Game server: ${GAME_SERVER}"
echo "Source path: ${SOURCE_PATH}"
echo "Patch path:  ${PATCH_PATH}"

# Tee all output to a log file so the dashboard can read it,
# while keeping stdout for `docker compose logs`.
LOG_FILE="/app/logs/${TEAM_ID}_agent.log"
exec > >(tee -a "$LOG_FILE") 2>&1

# Launch the appropriate agent
case "$TEAM_ID" in
  claude)
    exec python3 -u /app/harnesses/claude/agent.py
    ;;
  gpt)
    exec bash /app/harnesses/run_loop.sh gpt
    ;;
esac
