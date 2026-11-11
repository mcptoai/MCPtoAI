#!/usr/bin/env bash
# Local-only SIWC 0.2.8 preview preflight. No real OAuth, credentials or network needed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
python3 - <<'PY'
from pathlib import Path
s=Path('device-agent/mcptoai_agent/siwc_gate.py').read_text()
assert 'SIWC_ALLOW_WEB = False' in s, 'Web SIWC must remain hard-coded false'
assert 'if origin != \'desktop-local\':' in s, 'Relay deny guard missing'
print('PASS: SIWC web disabled at gate')
PY
for file in desktop/src/main.js desktop/src/preload.js desktop/src/renderer.js; do
  node --check "$file"
done
printf 'PASS: Desktop JavaScript syntax\n'
cd device-agent
if [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python; else PYTHON=python3; fi
"$PYTHON" -m pytest -q tests/test_siwc_auth_026.py tests/test_siwc_responses_026.py tests/test_siwc_gate_028.py tests/test_siwc_owner_028.py tests/test_siwc_token_canary_028.py tests/test_siwc_multiprocess_028.py tests/test_siwc_transport_boundary_028.py tests/test_siwc_owner_transition_028.py tests/test_siwc_ipc_boundary_028.py tests/test_siwc_future_web_policy_028.py tests/test_siwc_legacy_skills_contract_028.py tests/test_siwc_relay_entry_028.py
printf 'PASS: synthetic SIWC local acceptance regression set\n'
