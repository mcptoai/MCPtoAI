#!/usr/bin/env bash
# Destructive QA wrapper: NEVER use a production profile.
set -euo pipefail
ROOT="$(mktemp -d "${TMPDIR:-/tmp}/mcptoai-activity-qa.XXXXXXXX")"
trap 'rm -rf -- "$ROOT"' EXIT
: > "$ROOT/.mcptoai-activity-test-only"
export HOME="$ROOT"
export APPDATA="$ROOT"
export XDG_CONFIG_HOME="$ROOT"
PYTHON="${PYTHON:-python3}"
AGENT="${AGENT:?Set AGENT to the test mcptoai-agent executable}"
PYTHONPATH="${PYTHONPATH:-}:$(cd "$(dirname "$0")/../device-agent" && pwd)" "$PYTHON" -m mcptoai_agent.activity_test_guard "$ROOT"
"$AGENT" activity-clear --confirm
