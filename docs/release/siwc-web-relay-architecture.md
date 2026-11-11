# SIWC Web/Relay architecture — future approval-gated integration

## Intended user journey
1. User signs into ChatGPT through the macOS Device Agent using OAuth PKCE.
2. Agent binds the SIWC vault record to the authenticated MCPtoAI Auth0 owner.
3. Same owner signs into app.mcptoai.com using Auth0 and selects a paired online device.
4. User selects ChatGPT provider and initiates a web chat turn.
5. Backend authenticates the web session, verifies device ownership and pairing, and sends the turn over the existing authenticated device WebSocket.
6. Device Agent independently validates the authorized owner, target device, message/session identity, and user-initiated turn before retrieving SIWC credentials from its local OS vault.
7. Device Agent invokes OpenAI directly and returns only response events through relay to web. SIWC OAuth tokens and refresh credentials never traverse relay, web, browser, or telemetry.

## Approval and rollout
- `SIWC_ALLOW_WEB=False` is immutable for the current release. OpenAI's written approval and authorized client scope are prerequisites for enabling web-mediated SIWC use.
- Changing the flag alone must never grant web access. `siwc_policy.authorize_web_turn` requires a trusted `WebTurnAuthorization` context. No production relay path constructs this context yet.
- The verification context MUST be derived from authenticated backend/device transport and cryptographically or otherwise securely bound to the turn, not accepted from client JSON. Web-origin claims are untrusted.
- Future integration: backend emits an authenticated per-turn authorization envelope bound to Auth0 owner, device ID, session ID, message UUID, issuance/expiry and purpose; Agent verifies signature or MAC, issuer, audience, nonce/replay, owner binding and active device connection. Keys must not be exposed to browser.
- Reject stale, duplicate, cross-owner, cross-device, revoked, unattended, and unknown-origin requests before vault access. Existing turn receipt deduplication is not a substitute for authentication.
- When Mac/Agent is offline, SIWC via web is unavailable. No server-side token copy or fallback provider.
- Provider metadata may be shown as unavailable/coming soon, but web execution must remain denied until all checks and approval are complete.

## Outstanding implementation and acceptance work
- Backend authenticated per-turn authorization envelope and Web UI integration.
- Agent verification of envelope using a trusted backend key, connection-bound device identity, expiration, replay store, account re-check and logout revocation.
- Distinct trusted Desktop IPC provenance; do not trust `user_initiated=True` from arbitrary local JSONL.
- End-to-end adversarial tests on Mac and Ubuntu, network capture/log canary, signed Windows/macOS packaging and OTA regression.

## Current implementation
- `siwc_policy.py` models future authorization requirements with default deny.
- It is intentionally not wired to relay execution because no trusted backend envelope verifier exists yet. Current provider's unknown-origin guard remains active.
