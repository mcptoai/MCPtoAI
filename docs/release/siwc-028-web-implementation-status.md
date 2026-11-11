# 0.2.8 SIWC web/relay — implementation checkpoint (NOT RELEASE READY)

Requested: opt-in Desktop web permission (default off), owner-bound interactive turns only, global server kill switch, web usage UX, 7-language privacy notice.

Completed in local working tree:
- Desktop web opt-in toggle and first-use explanation; independent `siwc-web` CLI setting; Desktop Preview off also disables web permission.
- Server staging files: `/home/bktyserver/mcptoai/shared/siwc-web-policy.json` defaults false; backend `relay/siwc_web_policy.py` fail-closed reader; policy endpoint `api/siwc/web-policy/`; consumer denies SIWC web messages if switch false or verified per-turn authorization unavailable.
- Agent `siwc_policy.py` requires both local permissions, fresh server switch, verified owner/device/session/turn/SIWC owner/no-replay/no-jobs; tests use synthetic claims and do NOT prove a live backend-authenticated envelope.
- Desktop initial consent disclosure and `Using ChatGPT plan` model label.

BLOCKING (do not package or activate web SIWC):
- Authenticated backend per-turn envelope bound to owner, device, session, turn ID, expiry and replay nonce, verified by Agent. Current relay consumer denies all web SIWC messages, even when kill switch is on.
- Provider invocation must consume verified context; currently `siwc_gate.py` still denies all non-desktop origins.
- Server web chat indicator, Manage usage and 429 primary action not implemented.
- Seven-language privacy copy and MCPtoAI_Server PR not implemented. Marketing site on server is `site-src` and currently has only `content/legal/en.json`.
- No signed packaged Mac/Windows test, real OAuth, live web test or approval confirmation.

Do not enable the server kill switch until all blocking items and adversarial tests are complete.
