#!/bin/bash
# Launch all LLM agents.
#
# Default: start agents in Docker containers (recommended for security).
# Use --host to run agents directly on the host (legacy mode).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

if [ "${1:-}" = "--host" ]; then
    # Legacy host-based mode (agents run as local processes)
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)

    echo "Launching all LLM agents (host mode)..."
    echo "Logs will be written to $LOG_DIR/"
    echo ""

    echo "Starting Claude (Sonnet 4.6)..."
    bash "$ROOT_DIR/harnesses/claude/run.sh" \
        > "$LOG_DIR/claude_${TIMESTAMP}.log" 2>&1 &
    CLAUDE_PID=$!
    echo "  PID: $CLAUDE_PID | Log: $LOG_DIR/claude_${TIMESTAMP}.log"

    echo "Starting GPT (GPT-5.3 Codex)..."
    bash "$ROOT_DIR/harnesses/codex/run.sh" \
        > "$LOG_DIR/gpt_${TIMESTAMP}.log" 2>&1 &
    GPT_PID=$!
    echo "  PID: $GPT_PID | Log: $LOG_DIR/gpt_${TIMESTAMP}.log"

    echo ""
    echo "All agents launched! Monitor with:"
    echo "  tail -f $LOG_DIR/claude_${TIMESTAMP}.log"
    echo "  tail -f $LOG_DIR/gpt_${TIMESTAMP}.log"
    echo ""
    echo "To stop all agents:"
    echo "  kill $CLAUDE_PID $GPT_PID"
    echo ""
    wait
else
    # Containerized mode (recommended)
    echo "Launching all LLM agents in Docker containers..."
    echo ""
    echo "Ensure API keys are set in .env (see .env.example)"
    echo ""

    docker compose -f "$ROOT_DIR/docker-compose.yml" up -d agent-claude agent-gpt

    echo ""
    echo "All agents launched! Monitor with:"
    echo "  docker compose logs -f agent-claude"
    echo "  docker compose logs -f agent-gpt"
    echo ""
    echo "To stop agents:"
    echo "  docker compose stop agent-claude agent-gpt"
fi
