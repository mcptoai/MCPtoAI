# MCPtoAI Desktop v0.2.14 — macOS and Windows

MCPtoAI Desktop and its bundled Device Agent are both **v0.2.14**; Linux CLI and Docker remain independently versioned at **v0.3.1**. Official installers were built from Core commit `b7dd1840d49db8774c1bf6432c8b6a2d52baed35` (the public source commit may differ).

## Improvements

- **Send original HEIC/HEIF files to your Mac:** a trusted user-approved device transfer supports files up to **50 MiB** (50 × 1024 × 1024 bytes) while preserving the original image and SHA-256. Device transfers do not mean files are automatically sent to a model. This 50 MiB ceiling does **not** raise ordinary chat document or chat-image limits (10 MiB/file, 20 MiB/turn).
- **Create approved subfolders:** `create_folder` supports a nested relative path within an approved workspace, including missing intermediate directories. A new folder requires local confirmation; symlinks, junctions, case aliases, path escapes and collisions are rejected. Safe already-existing exact folders succeed without modification. User confirmation is required for explicit new creation.
- **Choose a subfolder when sending a file from the web or your phone to your Mac:** select a subfolder within an approved Mac workspace. If it does not exist, MCPtoAI can create it after you confirm the transfer on your Mac and the file is validated. Existing files are never overwritten, and access stays within the workspace you approved.
- **Save an image from chat to your Mac:** after an explicit web opt-in, compatible macOS devices request a trusted native confirmation for the chosen approved workspace. Saving is a **save-only** operation: it does not automatically send the local path to the model, invoke a follow-up device tool or produce a processed derivative in the same conversation turn.
- **Windows OneDrive Known Folders:** Desktop, Documents and Downloads use Windows Known Folder resolution, including supported OneDrive folder redirection and Microsoft cloud placeholders, while continuing to reject unsafe reparse points and traversal.
- **Turkish characters and folder results:** Windows device-tool output preserves Turkish letters (`ğ ş ı ö ç ü`); safe `create_folder` calls for an already-existing directory return a localized successful `already_exists` outcome without creating anything.
- **Reliability:** improved long-transfer approval lifetime, Agent handover and strict device checks on Mac and Windows.

## Installation and package verification

Get MCPtoAI from the [official Downloads page](https://mcptoai.com/downloads/). The macOS installer is signed and Apple-notarized; the Windows installer is signed by BKTY LTD. You can verify your download using the SHA-256 checksums below.

| Artifact | SHA-256 |
| --- | --- |
| `MCPtoAI-0.2.14-arm64.dmg` | `4eca79a358e38ee26d274b06132ca3f4da45d3548e6799c4121d57e2740d20e2` |
| `MCPtoAI-0.2.14-arm64.zip` (updater) | `5735b7892969741573bc2a6e137b606ace0b5527bc8e4801fcb75f62fc5f454d` |
| `MCPtoAI-0.2.14-x64-Setup.exe` | `6d106d91da6a944977f6e523434a270396757a041e6487d5252d04ef31ad56cd` |

Version 0.2.14 passed installation and device checks on Mac (**11/11**) and Windows (**14/14**).

## Version and release history

- **v0.2.10** preceded the 0.2.13 public Desktop release.
- **v0.2.11 and v0.2.12** were **tagged but not publicly released**; neither is an upgrade prerequisite.
- **v0.2.13** was the previous published Desktop version.
- **v0.2.14** adds the Mac file-transfer, approved-folder and chat-image-save improvements described above, alongside Windows folder compatibility fixes.

## Limitations and scope

- Native device-file transfer / chat-image save with trusted Mac approval is **macOS-only**. Windows native device-file inbound upload still awaits separate trusted approval / IPC work; OneDrive `create_folder` support is not Windows upload support.
- Saving a chat image does **not** automatically process it in the same turn; same-turn processing and a separate second tool approval are deferred to a later release.
- Browser automation, scheduled tools and an expanded remote action policy are **not** part of this release.
- Provider image processing and token estimates depend on the provider and model; local permissions still apply.

For security reports, see [SECURITY.md](../SECURITY.md).
