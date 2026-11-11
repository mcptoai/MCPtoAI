# PR C — SIWC 0.2.8 acceptance gates

Status: NOT ACCEPTED. Preview is disabled by default. No production release, merge or OTA until all gates have code and passing test evidence. Prior mock tests do not establish production authorization.

Scope: local macOS/Windows Desktop + Device Agent only. Linux CLI, PyPI, Docker and web/relay SIWC are excluded. `SIWC_ALLOW_WEB` must be hard-coded false and cannot be overridden by users, environment variables or UI. Every relay-origin SIWC model request must fail at the invocation boundary with: `ChatGPT plan is available in the desktop app only for now`.

| # | Required gate | Evidence required (code + test; incomplete until verified) |
|---|---|---|
| 1 | `SIWC_ENABLED` defaults false; user can enable Desktop-local Preview in settings; enforcement at actual model invocation. `SIWC_ALLOW_WEB` constant false, relay rejected with user-facing message. | Provider invocation guard; Desktop settings/UI; direct/relay negative tests. **PENDING** |
| 2 | At login bind SIWC identity to MCPtoAI user identity in device-local secure storage; compare verified request user for every invocation, including local; reject mismatch. | Identity binding and verified caller propagation; mismatch tests. **PENDING** |
| 3 | Tokens only in OS Keychain/Credential Manager; never relay/server/log/event journal/replay; canary test. | Secret-store audit and canary instrumentation. **PENDING** |
| 4 | Only user-initiated turns; reject jobs/scheduled work/MCP sampling without explicit consent. | Invocation-origin enforcement; negative tests. **PENDING** |
| 5 | No automatic account/provider switching; clear 429/usage-limit message. | Error mapping and negative tests. **PENDING** |
| 6 | Refresh re-reads token after acquiring lock; no duplicate refresh if another process refreshed; show revocation failure on logout. | Refresh concurrency tests and UI logout test. **PENDING** |
| 7 | Button `Continue with ChatGPT`; first-login disclosure of account/plan usage; `Using ChatGPT plan` model indicator; `Manage usage` link; authorization name `MCPtoAI`; `Preview` label. | Desktop UI and UI tests. **PENDING** |
| 8 | Dynamic model list, no fixed model name. | Models API adapter and tests. **PENDING** |
| 9 | Privacy notice distinguishes local credential storage from cloud prompt processing; explicitly says web/relay plan use unavailable; 7-language MCPtoAI_Server marketing-site PR before live 0.2.8. | Privacy copy, translations, server PR. **PENDING** |
| 10 | macOS/Windows Desktop + Agent only; exclude Linux CLI and Docker. Signed test builds; no A8/OTA regression. | Build manifests, signed artifacts, integration/regression tests. **PENDING** |

Existing scaffold: `device-agent/mcptoai_agent/siwc_auth.py`, `providers/siwc_provider.py`, `providers/siwc_responses.py`, Desktop IPC `chatgpt:auth`; mocked tests `test_siwc_auth_026.py`, `test_siwc_responses_026.py`. These are starting points, **not** proof of acceptance.

Release hold: commercial client ID and any web authorization require written OpenAI confirmation. Do not activate relay SIWC in 0.2.8 under any circumstance.

## Implementation evidence — stage 1 (not full acceptance)
- `device-agent/mcptoai_agent/siwc_gate.py`: immutable `SIWC_ALLOW_WEB = False`; default-deny local Preview and origin checks.
- `device-agent/mcptoai_agent/providers/siwc_provider.py`: enforcement before token access and HTTP. Provider factory defaults to unknown origin; only Desktop local chat opts into `desktop-local` origin.
- `device-agent/mcptoai_agent/__main__.py`: `siwc-preview` local CLI, Desktop local chat invocation context.
- `desktop/src/main.js`, `desktop/src/preload.js`, `desktop/renderer.js`: Preview settings toggle, local IPC preflight; web cannot toggle via relay.
- `device-agent/tests/test_siwc_gate_028.py`: web denial, default-off, user-turn and pre-token denial.
- Validation: 491 passed, 6 skipped, 56 subtests; Desktop JS syntax checks passed.
- LIMITATION: identity binding (#2) and authenticated request-origin propagation are not yet implemented; current `desktop-local` origin is process-internal routing, not a verified user identity. Do not ship.

## Implementation evidence — stage 2 (owner binding)
- `siwc_auth.paired_owner()` reads `owner_sub` from the existing device-auth vault; missing pairing fails closed.
- New SIWC OAuth records include `mcptoai_owner_sub`; re-login, token access, refresh, status and logout verify current owner.
- Provider invocation gate checks owner before token supplier; missing/foreign/legacy unbound records are denied.
- `test_siwc_owner_028.py` verifies absent/mismatched/matching ownership and pre-token rejection.
- Full Device Agent suite: 497 passed, 6 skipped, 56 subtests. No live OAuth or signed build performed.
- LIMITATION: OS-session trust and cross-user desktop process authorization have not been independently audited. Legacy SIWC records without binding require controlled reconnect/migration; logout behavior needs UX follow-up. Gate #2 is not signed off until full end-to-end evidence exists.

## Implementation evidence — stage 3 token review (partial)
- Inspected `siwc_auth.py`, `secret_store.py`, `credential_lock.py`, and relay token references without exposing actual credentials.
- Identified redundant refresh after cross-process rotation: `refresh(expected_refresh_token=...)` now re-reads under lock and returns newly rotated, sufficiently valid access token without a second OAuth call.
- Added race tests for rotated valid token and rotated expired token; full Agent suite: 499 passed, 6 skipped, 56 subtests.
- Static search of Agent/Desktop for direct token printing/logging found no obvious SIWC token output. This is not a complete canary or live network audit.
- Outstanding: live OAuth/Keychain verification, Windows runtime checks, token canary through logs and relay, logout/revocation UX and broader refresh race tests. Do not mark gate #3 fully accepted.

## Stage 3 — synthetic token canary and offline revocation tests
- Added `test_siwc_token_canary_028.py`: synthetic credential absent from status output; HTTP OAuth failure suppresses sensitive response details; offline logout clears local SIWC record and reports `revoked: false`.
- Full Agent suite: 502 passed, 6 skipped, 56 subtests.
- No real credential, live OpenAI session, relay network capture, or OS Keychain entry was accessed by these tests.
- Remaining: independent two-process OS-lock integration, relay/log canary end-to-end, live OS vault validation, and revocation UX. Gate #3 remains pending.

## Stage 3 — actual two-process refresh integration (local Mac)
- Added `test_siwc_multiprocess_028.py`: two spawned Python processes read the same expired synthetic token, synchronize before refresh, and contend on a real macOS file lock.
- Exactly one synthetic OAuth refresh call; both processes return the same rotated access token; final synthetic store retains the rotated refresh token.
- Full local Agent suite: 503 passed, 6 skipped, 56 subtests. No real OS vault or OpenAI network call.
- GitHub Actions usage constraint: `client-ci.yml`, `package-security.yml`, and Windows regression workflow run on pull_request, so pushing to the open PR can trigger paid hosted runners. Changes held locally pending workflow optimization/approval.

## Stage 3 — synthetic provider transport boundary tests
- Added `test_siwc_transport_boundary_028.py`: relay origin, non-user-initiated desktop turn and disabled Preview all reject before token supplier or HTTP client invocation; denial output contains no synthetic token.
- Full local Agent suite: 507 passed, 6 skipped, 56 subtests.
- Source inspection: Desktop IPC `chat:local` delegates to `desktop-chat-jsonl`; the latter marks requests desktop-local/user-initiated. This is a process-boundary assumption, not proof that an untrusted local process cannot inject a message.
- No full Desktop-to-relay packet capture or OS credential inspection yet. Gate #3 remains pending.
- Per user instruction, keep commits local until all tests finish; avoid GitHub Actions consumption.

## Stage 3 — owner transition regression (local Mac)
- `test_siwc_owner_transition_028.py`: switching from owner A to owner B denies access-token reads and refresh before HTTP; denies logout/revocation/deletion of A's credential; provider gate denies before calling token supplier.
- All records and tokens are synthetic. Full local Device Agent suite: 510 passed, 6 skipped, 56 subtests.
- Desktop IPC user-initiation trust boundary remains open for dedicated negative testing and review. No GitHub push or Actions run.

## Stage 4 — Desktop IPC wiring review (local Mac)
- `test_siwc_ipc_boundary_028.py`: verifies Desktop `chat:local` checks Preview and uses `desktop-chat-jsonl`, the agent labels that entrypoint desktop-local/user-initiated, and other provider-factory entrypoints default to unknown/false.
- These are source wiring regressions, not runtime authentication tests. An arbitrary local process able to invoke the agent CLI with a crafted JSONL message may be treated as user-initiated; process caller provenance is not established by the current gate. This is an unresolved security design issue requiring mitigation or explicit documented acceptance before SIWC release.
- Full local Agent suite: 513 passed, 6 skipped, 56 subtests. No Actions or push.

## Future Web/Relay SIWC design (approval-gated)
- Added `docs/release/siwc-web-relay-architecture.md` specifying Auth0 web owner -> authenticated relay -> paired Agent -> local SIWC vault -> OpenAI, without sharing OAuth tokens.
- Added default-deny `siwc_policy.py` and six tests: even a future enabled switch rejects incomplete trusted owner/device/session/user-turn assertions; current switch rejects all web turns.
- Full Mac Device Agent suite: 519 passed, 6 skipped, 56 subtests.
- This is a policy scaffold and architecture specification, **not** completed backend attestation, cryptographic verification, or operational Web SIWC. Never enable the switch until those components, negative integration tests and OpenAI approval are complete.

## Legacy 0.2.6 SIWC skill compatibility
- Compared `origin/wip/026-layered-context` with current provider and relay wiring. The old relay used `make_provider(provider_cfg)` and the shared `AgentSession.run` / `run_capability` path; the new `c9f9def` origin gate intentionally denies the relay path.
- Added `test_siwc_legacy_skills_contract_028.py`: synthetic SIWC Responses tool call `load_skill`, matching tool-result `call_id`, follow-up model response, and `store=False` across both requests. The test passes with current provider without restoring unsafe web access.
- Full local Agent suite: 520 passed, 6 skipped, 56 subtests. This is not an end-to-end web/relay integration test; approval-gated backend attestation is still missing.

## Relay entry fail-closed regression
- Relay `_run_message` rejects selected/default ChatGPT provider before provider creation, skill loading or token lookup, including omitted provider with ChatGPT default.
- `test_siwc_relay_entry_028.py` adds two synthetic negative tests. Full Mac suite: 522 passed, 6 skipped, 56 subtests.
- This denial is permanent for the 0.2.8 Desktop-only scope. Backend-signed web turn authorization is out of scope and must be designed separately only after written OpenAI confirmation. Changing `SIWC_ALLOW_WEB` alone must never enable web turns.

## 0.2.8 scope freeze and live-test package
- Desktop local Preview only, default off; Web/relay SIWC always denied. The inert `siwc_policy.py` scaffold is retained but not extended. No backend signing or Agent verification work in this release.
- Offline local preflight: `bash device-agent/scripts/siwc-desktop-acceptance.sh`.
- Live Mac/Windows OAuth, Skills, user consent, privacy and signed-build evidence template: `docs/release/siwc-028-live-desktop-test-pack.md`.
- All ten gates remain pending until independently verified; a passing synthetic suite does not constitute release acceptance.
