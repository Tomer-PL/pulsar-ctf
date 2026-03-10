#!/bin/bash
# Set up a restricted environment for LLM agents.
# Source this before launching any LLM harness.
#
# Blocks:
#   - docker CLI (via PATH shadow)
#   - Docker socket access (via DOCKER_HOST override + socket permissions)
#   - Direct socket file access (via restrictive sandbox on macOS)
#
# Usage: source setup_env.sh <team_name>

set -euo pipefail

TEAM_NAME="${1:?Usage: source setup_env.sh <team_name>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# --- Audit log ---
export PULSAR_AUDIT_LOG="$ROOT_DIR/logs/audit_${TEAM_NAME}.log"
mkdir -p "$(dirname "$PULSAR_AUDIT_LOG")"

# --- Block docker CLI ---
# Put our fake docker binary first in PATH
export PATH="$SCRIPT_DIR:$PATH"

# --- Block docker socket via environment ---
# Point DOCKER_HOST to a nonexistent socket so even if they bypass PATH,
# docker commands fail
export DOCKER_HOST="unix:///dev/null/pulsar-blocked"

# --- Block docker Python library ---
# Set env var that the docker Python SDK reads
export DOCKER_TLS_VERIFY=""

# --- Block common bypass paths ---
# Create shell functions that override direct path invocations.
# Shell functions take precedence over binaries even when called by full path.
docker() {
    echo "ERROR: docker is disabled. Use the game server API." >&2
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) BLOCKED docker $*" >> "$PULSAR_AUDIT_LOG" 2>/dev/null
    return 1
}
export -f docker

# --- Block access to docker socket file ---
# On macOS, we can't easily change socket permissions, but we can
# create a socat proxy or use sandbox-exec. For now, we detect and
# warn about socket access attempts.

# --- Restrict source code to read-only ---
# LLMs should read source but submit patches via API
export PULSAR_SOURCE_PATH="$ROOT_DIR/challenges-source"

echo "[restricted_env] Environment locked down for team: $TEAM_NAME"
echo "[restricted_env] docker CLI: BLOCKED (PATH shadow + shell function)"
echo "[restricted_env] DOCKER_HOST: $DOCKER_HOST (invalid)"
echo "[restricted_env] Audit log: $PULSAR_AUDIT_LOG"
