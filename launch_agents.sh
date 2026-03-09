#!/bin/bash
# Launch all three LLM agents in background processes with logging
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "Launching all LLM agents..."
echo "Logs will be written to $LOG_DIR/"
echo ""

# Launch Claude
echo "Starting Claude (Sonnet 4.6)..."
bash "$ROOT_DIR/harnesses/claude/run.sh" \
    > "$LOG_DIR/claude_${TIMESTAMP}.log" 2>&1 &
CLAUDE_PID=$!
echo "  PID: $CLAUDE_PID | Log: $LOG_DIR/claude_${TIMESTAMP}.log"

# Launch GPT
echo "Starting GPT (GPT-5.3 Codex)..."
bash "$ROOT_DIR/harnesses/codex/run.sh" \
    > "$LOG_DIR/gpt_${TIMESTAMP}.log" 2>&1 &
GPT_PID=$!
echo "  PID: $GPT_PID | Log: $LOG_DIR/gpt_${TIMESTAMP}.log"

# Launch Gemini
echo "Starting Gemini (Gemini 3.1 Pro)..."
bash "$ROOT_DIR/harnesses/gemini/run.sh" \
    > "$LOG_DIR/gemini_${TIMESTAMP}.log" 2>&1 &
GEMINI_PID=$!
echo "  PID: $GEMINI_PID | Log: $LOG_DIR/gemini_${TIMESTAMP}.log"

echo ""
echo "All agents launched! Monitor with:"
echo "  tail -f $LOG_DIR/claude_${TIMESTAMP}.log"
echo "  tail -f $LOG_DIR/gpt_${TIMESTAMP}.log"
echo "  tail -f $LOG_DIR/gemini_${TIMESTAMP}.log"
echo ""
echo "Scoreboard: http://localhost:8888/"
echo ""
echo "To stop all agents:"
echo "  kill $CLAUDE_PID $GPT_PID $GEMINI_PID"
echo ""

# Wait for all to finish
wait
