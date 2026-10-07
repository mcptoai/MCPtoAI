# Security Policy

Security is a core part of MCPtoAI because the Device Agent can interact with local files, terminal commands and connected MCP tools.

## Supported versions

MCPtoAI is currently in the `0.x` development series. Security fixes are normally applied to the latest available release. Users should keep MCPtoAI Desktop, the Device Agent and the CLI up to date.

| Version | Supported |
| --- | --- |
| Latest `0.x` release | ✅ |
| Older `0.x` releases | Best effort |

## Reporting a vulnerability

**Please do not open a public GitHub issue for a suspected security vulnerability.**

Use GitHub's private vulnerability reporting / Security Advisory flow for this repository when available. If that option is not available, contact BKTY LTD through the official MCPtoAI website and clearly mark the report as a security issue:

https://mcptoai.com

A useful report should include:

- A clear description of the vulnerability and its impact.
- The affected MCPtoAI version and operating system.
- Reproduction steps or a minimal proof of concept.
- Relevant logs, screenshots or traces with secrets removed.
- Whether the issue requires a paired account, local access, a malicious MCP server or another prerequisite.

Please do **not** include API keys, access tokens, private files or other credentials in the report.

## What we consider security-sensitive

Examples include:

- Authentication or device-pairing bypasses.
- Unauthorized access outside the configured filesystem workspace.
- Command execution that bypasses local permission controls.
- Credential or API-key disclosure.
- MCP tool invocation that bypasses expected user controls.
- Update-channel, signing or package-integrity issues.
- Cross-device access or session-isolation failures.

## Disclosure

We ask reporters to allow reasonable time for investigation and remediation before public disclosure. We will aim to acknowledge actionable reports promptly and coordinate disclosure when a fix is available.

## Security design notes

MCPtoAI separates the hosted coordination layer from device-side execution. Local capabilities are executed by the Device Agent on the paired computer and are subject to local configuration and operating-system permissions. Provider credentials should never be committed to this repository.
