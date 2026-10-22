# MCPtoAI 0.2.3 — Release notes (public source preparation; stable not published)

**Status:** public source preparation only; stable 0.2.3 is not published. The macOS and Windows canary OTA upgrade from 0.1.18 to 0.2.3 was completed successfully on real devices. This is not a claim of general stable-channel availability.

## Highlights since 0.1.18

- **Skills (macOS and Windows only):** managed agent skills, preflight validation, controlled skill-file/data access and policy enforcement. **Linux Skills parity is not claimed.**
- **Universal File Artifacts:** explicit user-approved device-to-chat transfers; supported document, audio, image and video formats; authenticated download and in-chat MP4 playback. Artifact limits, workspace boundaries, expiration and server pruning are enforced. A file is not uploaded merely by returning its local path.
- **Protected locations:** safeguards for agent credentials and application data, cloud secrets, browser profiles, shell histories, SSH/other private keys and sensitive filenames. Windows AppData is protected. The policy applies to built-in file tools and resolves symbolic links and Windows path aliases.
- **Pre-approval validation:** file path, regular-file status, extension, size and workspace checks run before asking the user to approve. Artifact confirmation cards display agent-derived file type/size, and write cards distinguish new files from overwrites.
- **Four tool result states:** `completed`, `failed`, `blocked`, and `denied`, with backward-compatible handling for older agents. Web displays icons and text, not only colors.
- **0.2.3 security fix:** model-provided `_approval_meta` is removed from tool arguments; only the agent may attach computed metadata for `send_artifact` and `write_file`. Web ignores metadata for all other tools. The new anti-spoof tests also cover `run_command`.
- **Video usability:** native player controls plus accessible five-second (short clips) or ten-second seek buttons (long clips).
- **Maintenance:** artifact cleanup includes expired records, orphan cleanup and dry-run reporting; storage/disk monitoring has alert thresholds.

## Security model and known limitations

- **Terminal commands can access anything your OS account can; approval cards are the only barrier.** `run_command`, `run_in_project`, background jobs and external MCP tools are not sandboxed by the built-in file-path protection policy.
- **Keynote .key files are blocked because the extension is also used for private keys.** No Keynote-specific exception is provided in 0.2.3.
- Linux wheel is **unsigned**; verify its published SHA-256/SHA-512 and provenance. PyPI trusted publishing/attestations are a future consideration, not a feature already provided.
- The security policy reduces accidental sensitive file access but is not an OS-level security boundary against arbitrary commands executed with the user's privileges.
- File-transfer/playback validation performed on Linux does not by itself prove every macOS or Windows user workflow; final release gate must include real transfers from both platforms.
- Existing long-running chats may temporarily disconnect during separately authorized web restarts or Agent upgrades. Preserving Keychain, config and device identity is mandatory.

## Release boundary

This document is **read-only planning**. No installation, notarization, signing, backend migration, web activation, upload to release directories, change to update manifests or public release is authorized by these notes. Source preparation and QA do not turn on an OTA channel.

## Verified canary OTA upgrade (22 October 2026)

- macOS: user-driven 0.1.18 to 0.2.3 update completed; installed desktop and bundled Device Agent report 0.2.3. Developer ID signature verification, Gatekeeper acceptance and notarization stapling checks passed. The agent binary matched the tested build and passed 28/28 integrity markers. Exactly one agent `connect` process was running.
- Windows: user-driven 0.1.18 to 0.2.3 update completed; installed desktop and agent report 0.2.3. Installer and installed executable Authenticode signatures were valid (BKTY LTD). Downloaded OTA installer SHA-256 matched the canary manifest. Exactly one agent `connect` process was running.
- These were controlled canary tests, not a stable-channel rollout. The transport was not independently proven to use differential downloads. macOS launchd registration metadata retained a stale parent bundle version even though installed binaries were verified at 0.2.3. Linux parity for managed Skills is not claimed.
