# Contributing to MCPtoAI

Thanks for your interest in MCPtoAI.

This repository contains the source of the MCPtoAI Desktop app. The Device Agent, hosted web app and relay are not part of this repository. Contributions should stay focused on the Desktop app unless a maintainer explicitly asks for something broader. Bug reports and feature requests about any part of MCPtoAI are welcome as issues.

## Before you start

- Search existing issues before opening a new one.
- Use the bug report template for reproducible defects.
- Use the feature request template for product ideas or workflow improvements.
- For security vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Development setup

```text
desktop/   Electron Desktop app
```

Install the official MCPtoAI release from <https://mcptoai.com/downloads/> first: in development
mode the Desktop app uses the Device Agent installed by the release.

```bash
cd desktop
npm install
npm start
```

Packaging scripts are defined in `desktop/package.json`. Building the Device Agent, signing and
notarization require maintainer-only components and credentials and are not expected for normal
contributions.

## Pull requests

Keep pull requests focused and easy to review.

A good pull request should:

- Explain the problem being solved.
- Describe the implementation briefly.
- Mention affected platforms.
- Include manual test steps.
- Avoid unrelated refactors.
- Avoid committing generated release artifacts, secrets or local configuration.

If the change affects permissions, command execution, filesystem access, authentication, MCP calls, provider credentials or the update path, call that out explicitly in the PR description.

## Coding expectations

- Prefer clear, maintainable code over clever abstractions.
- Preserve existing platform behavior unless the change intentionally modifies it.
- Treat all external input, tool arguments, paths and process execution as security-sensitive.
- Never add real API keys, tokens, cookies, certificates or signing credentials to examples or tests.
- Keep user-facing error messages actionable without exposing secrets.

## Testing

Before opening a PR, test the relevant component on the platform you changed where possible.

For Desktop changes, verify that the app starts and that the affected UI and Device Agent workflow behave as expected, on each platform you changed where possible.

## Commit messages

Use short, descriptive commit messages. Conventional-style prefixes are welcome but not required, for example:

```text
fix: preserve workspace boundary on path resolution
feat: add provider model refresh
docs: clarify installation steps
```

## License

By contributing, you agree that your contributions will be licensed under the repository's [MIT License](LICENSE).
