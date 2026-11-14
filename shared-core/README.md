# PR-B: Shared Agent Core (work in progress)

This directory is a **pre-release extraction workspace**, not a published PyPI package.
It begins with the side-effect-free replay-journal pruning primitive, verified
AST-equivalent to both existing implementations. The Desktop and Linux agents
continue using their existing implementations until dependency packaging and
compatibility wrappers are reviewed and tested together.

## Next steps before PR-B can merge

1. Move common pure modules into `mcptoai_core` and provide legacy import wrappers.
2. Define a single installable package/dependency strategy for source builds,
   PyInstaller, PyPI, systemd and Docker; avoid local path dependencies in releases.
3. Extract relay/reconnect/replay core behind explicit platform ports while keeping
   Desktop handover and Linux lifecycle separate.
4. Run full Desktop and Linux regression suites, import compatibility tests and
   clean-install packaging tests in CI.

Do not deploy or tag this work in its current state.

## Optional shared network classifier integration

Both legacy `net.py` modules now import `mcptoai_core.network.is_connection_reset`
when the shared distribution is installed. They retain an AST-equivalent fallback
for standalone release packages that do not yet bundle the shared distribution.
This is intentionally a transitional compatibility layer, **not** the final
single-source implementation. CI tests the shared import path and fallback
parity; release packaging must bundle shared-core before removing fallbacks.

## Replay migration

`mcptoai_core.replay.parse_replay_request` is shared by both relay clients
with a standalone fallback. Linux's existing rejection of turn-mode requests
containing `after_seq` is preserved through `reject_turn_cursor=True`;
Desktop retains its current permissive behavior. Event replay socket delivery,
active-turn bookkeeping, approval handling and persistent journal storage
remain platform-local pending separate compatibility and lifecycle work.

## Replay batch and journal migration

Both relay implementations now delegate cursor-based batch selection and
completion envelope construction to the shared pure replay module. Desktop's
`turn_active` completion extension is preserved, as is Linux's legacy
completion shape. Both event journals use the shared TTL pruning primitive
when installed and retain standalone fallbacks. **Socket delivery, approval
state, durable persistence and event turn bookkeeping remain in their
existing platform adapters** until separate extraction and compatibility tests.

## Receipt deduplication

Both legacy `MessageReceiptStore` implementations now call the shared pure
receipt pruning policy, retaining file storage and atomic mode-0600 writes
locally. Claim/finish/status methods remain unchanged; they must not be
replaced without separate durability, restart and race-condition tests.

## Event envelopes

Desktop and Linux now construct event envelopes through the same pure helper,
retaining the optional `turn_id` wire field and all existing per-platform
storage and send behavior. This change does not introduce new capabilities.

## WebSocket replay sender

The shared `send_replay_events` coroutine now handles ordered replay batches,
connection-identity checks, disconnect/failure exits, cursor advancement and
cancellation propagation. Platform adapters retain socket creation, reconnect
policy, turn state, approvals, and completion-specific fields. Standalone
fallbacks remain until both release builds package the shared wheel.

## Session state bounds

Session eviction is now shared and prunes event journals, sequence cursors,
turn state and per-turn replay history consistently. Platform adapters still
own their in-memory dictionaries and the durable journal lifecycle.

## Durable journal safety boundary

Both agents now use the same pure allowlist to persist only text, done, error,
resolved approval metadata, and non-actionable interrupted approvals. The
filesystem locking, atomic writes, retry timers, path ownership and lifecycle
remain in the platform adapters; no executable approvals are restored.
