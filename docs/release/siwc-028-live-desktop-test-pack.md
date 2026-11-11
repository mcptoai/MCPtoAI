# SIWC 0.2.8 — Desktop-local Preview acceptance package

**Scope:** Desktop local chat only (macOS and Windows); default disabled. Web/relay, scheduled jobs, Linux CLI and Docker excluded. `SIWC_ALLOW_WEB=False` is immutable in 0.2.8. The future-web policy scaffold remains inert and must not be extended in this release. No backend-signed web authorization work is in scope. No release until the 10 gates in `pr-c-siwc-acceptance.md` are signed off.

## Offline preflight (Mac)

From repository root: `bash device-agent/scripts/siwc-desktop-acceptance.sh`. This checks hardcoded web denial, Desktop JS syntax and synthetic SIWC regression tests. It **does not** prove real OAuth login, OS Keychain storage, actual Desktop caller provenance, or signed Windows/macOS packaging.

## Live test operator checklist — use a dedicated test account

1. Start signed test Desktop and paired Agent; verify Preview is **off** and ChatGPT plan cannot make a model call.
2. Enable Preview explicitly in Desktop settings; verify disclosure, `Continue with ChatGPT`, `Preview`, `Using ChatGPT plan`, and usage-management link. Record screenshots with tokens, user IDs and personal content redacted.
3. Complete real ChatGPT OAuth PKCE in system browser; verify Desktop reports connected and dynamic model list is returned (no hardcoded model). Do not copy tokens into tickets, chat or logs.
4. In Desktop **local** chat, send a user-initiated text prompt; verify successful response and selected-model indicator.
5. Invoke `load_skill` and one read-only tool through the ordinary `AgentSession` approval flow; verify skill context, tool-result continuity and final answer. Reject a sensitive tool approval and confirm no subsequent execution.
6. Switch paired MCPtoAI owner; confirm old owner's SIWC credential is unusable, cannot be refreshed or revoked by the new owner, and reconnect is required.
7. Trigger a deliberate invalid/revoked login in a controlled test; verify actionable error and no token or OAuth response body in Desktop logs, Agent logs, relay messages, event journal or screenshots.
8. Test usage-limit (429) behavior without provider fallback, then sign out and confirm local credential removal and clear revocation status.
9. In Web, attempt both explicit `provider=chatgpt` and default-ChatGPT requests; confirm the standard Desktop-only denial before tools or token access. Verify other Web providers remain functional.
10. Run macOS signed package and Windows signed package tests, agent handover/OTA regression, and all 10 acceptance gates. Record version, OS, build hash, date, result and redacted evidence per step.

## Evidence record template

| Gate | Mac result/evidence | Windows result/evidence | Reviewer/date |
|---|---|---|---|
| 1 Default off / local-only | Pending | Pending | |
| 2 Account owner / caller trust | Pending | Pending | |
| 3 OS vault / no leakage | Pending | Pending | |
| 4 User-initiated only | Pending | Pending | |
| 5 No fallback / 429 | Pending | Pending | |
| 6 Refresh / logout | Pending | Pending | |
| 7 OAuth UI/disclosure | Pending | Pending | |
| 8 Dynamic models | Pending | Pending | |
| 9 Privacy / seven languages | Pending | Pending | |
| 10 Signed builds / A8 / OTA | Pending | Pending | |

**Release blockers:** Official OpenAI commercial authorization, authenticated Desktop user-initiation boundary review, live macOS and Windows acceptance, signed builds and required privacy copy. Never mark a gate passed based on mock tests alone.
