# MCPtoAI 0.2.3 — Release notes

MCPtoAI 0.2.3 improves how your paired computer handles local tools, sensitive files, and approved file transfers. Features vary by operating system.

## What's new

- **Skills on macOS and Windows:** manage agent skills with preflight checks, access restrictions for skill files and data, and device-side policy enforcement. Managed Skills are not yet available on Linux.
- **Universal File Artifacts:** send supported documents, images, audio, and video from a paired device to chat after explicit approval. Transfers use authenticated downloads, file-size and workspace checks, expiration limits, and cleanup. Chat can play supported MP4 videos. Returning a file path alone does not upload that file.
- **Protected locations:** built-in file tools check sensitive directories and filenames, including application credentials, browser profiles, SSH keys, shell histories, and Windows AppData. Symlinks and Windows path aliases are resolved before file access.
- **Checks before approval:** file paths, file type, extension, size, and permitted workspace are checked before a confirmation prompt appears. Approval cards identify file types and sizes and distinguish creating a file from overwriting one.
- **Clearer tool results:** actions distinguish `completed`, `failed`, `blocked`, and `denied`. Statuses are communicated with text and icons, not color alone.
- **Safer approval details:** the agent, not model-supplied tool arguments, determines file metadata shown in approval prompts for supported file operations.
- **Video controls:** in-chat playback includes native controls and accessible seek buttons, using five-second steps for short clips and ten-second steps for longer clips.

## Security and known limitations

- **Terminal commands are not sandboxed.** If terminal access is enabled and a command is approved or otherwise permitted, it can access resources available to your operating-system account. The protected-file policy for built-in file tools does not sandbox `run_command`, `run_in_project`, background jobs, or external MCP tools. Review commands before approving them.
- **Keynote `.key` files are blocked.** The `.key` extension is also used for private keys, so this version does not provide a Keynote-specific exception.
- **Linux wheel packages are not cryptographically signed.** When installing a downloaded wheel, verify its published SHA-256 and SHA-512 checksums against a trusted release source. A checksum verifies the downloaded bytes against the reference; it is not a substitute for a trusted signature.
- Managed Skills currently support macOS and Windows, not Linux. File transfer availability and supported file types may vary by platform.
- Local permissions reduce unintended access, but they are not a substitute for operating-system account security and careful review of powerful tools.

## Upgrading

- **macOS and Windows:** when version 0.2.3 is offered in MCPtoAI Desktop, use **Check for Updates**, download the update, and choose **Restart & Install**. Reopen Desktop and confirm both the Desktop and Device Agent versions. Keep the device paired and review permissions after updating.
- **Linux CLI:** once 0.2.3 is published on PyPI, upgrade with `python3 -m pip install --upgrade mcptoai==0.2.3`, then check `mcptoai --version`. Do not use this command as evidence that the version is already published.
- **Docker:** once the 0.2.3 image is published, pull the versioned image `ghcr.io/mcptoai/mcptoai:0.2.3`. Keep your persistent configuration volume when replacing a container; verify the image digest from the trusted release information.

See [SECURITY.md](../SECURITY.md) for reporting security issues and the [Linux guide](../linux-agent/README.md) for platform-specific setup.
