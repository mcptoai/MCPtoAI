# MCPtoAI Desktop v0.2.13 — macOS and Windows

Released source: signed Core tag `v0.2.13`, commit `704270eae977e00dabd4451b48de191cc687aba8`. Desktop and bundled Device Agent are both version **0.2.13**. Linux CLI and Docker follow a separate version line (**0.3.1**) and are unchanged by this Desktop release.

## What's improved

- **Vision attachments:** More reliable JPEG, PNG, WebP and GIF chat images, HEIC/HEIF browser conversion when supported, and privacy-conscious removal of image metadata. Images within supported provider limits keep their original compressed pixels; oversized photographs and screenshots are resized as needed. A browser that cannot decode HEIC/HEIF displays an actionable message.
- **Visual context budgeting:** Images are budgeted using visual dimensions and conservative provider-specific image-token estimates rather than charging entire base64 attachments as text. Large PNG screenshots can reach the model without false `context_budget_exceeded` errors.
- **Documents and chat continuity:** Improved chat PDF/DOCX handling, localized attachment and context-capacity messages in the supported web languages, and safer continuity when switching models. Earlier attachment filenames are retained as context, without pretending a previous file's bytes remain available or searching the local filesystem for it.
- **Bounded file searches:** `find_files` has best-effort time, depth and result limits with explicit partial-result notices. An individual blocked OS filesystem call may still exceed the nominal ten-second deadline.
- **Safer device operation:** Existing device-side permissions and local approval are preserved; improved single-Agent handover/restart, Windows console-free supervisor, and file-transfer diagnostics.

## Installation

Download the **signed** Mac Apple Silicon DMG or Windows x64 Setup installer from [MCPtoAI Downloads](https://mcptoai.com/downloads/). The macOS package is Apple Developer ID signed, notarized and stapled; the Windows installer and bundled Agent are signed with a timestamp.

Official package SHA-256:

| Artifact | SHA-256 |
| --- | --- |
| `MCPtoAI-0.2.13-arm64.dmg` | `b0fc5d3ce686b46a21b76fe7d94701730e6f6f011b5eb852f0eb74db1867f7e9` |
| `MCPtoAI-0.2.13-arm64.zip` | `eef3384ace2df678cc3c9a3e7ec2d7168ffa0d6020d8d3081009c66c504c762b` |
| `MCPtoAI-0.2.13-x64-Setup.exe` | `34d31b2a478879b348c9da4e9e4785d7d648dd75750aff3f2cce1c36300f9048` |

## Version and release history

- **v0.2.10** was the preceding publicly available Desktop release.
- **v0.2.11** was tagged for testing but **not publicly released**; it was superseded.
- **v0.2.12** was tagged for testing but **not publicly released**; it was superseded.
- **v0.2.13** is the release candidate accepted after macOS and Windows device checks and user testing. It upgrades directly from v0.2.10; neither intermediate version is a required installation step.

## Known limitations

- macOS device-side inbound transfer requires explicit local approval. Original HEIC/HEIF **device-file inbound** remains unsupported; chat HEIC/HEIF conversion is a separate feature.
- Windows native inbound file transfer still requires a separate trusted approval/IPC implementation. A successful Windows **chat document** upload is not evidence that device-side inbound file transfer is supported.
- Browser automation, scheduled tasks and newly planned action capabilities are not included in v0.2.13. Existing action safety gates remain off by default where documented.
- Image processing and token budgeting remain provider/model-dependent; estimates are not provider billing guarantees.

The tag and binary verification are independent of production OTA, website publication or public GitHub Release creation. Those rollout steps require separate operator approval. For security reports, see [SECURITY.md](../SECURITY.md).
