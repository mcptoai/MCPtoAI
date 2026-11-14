# MCPtoAI Linux 0.3.1 — release notes (draft; not published)

Linux 0.3.1 fixes Docker workspace defaults, model discovery, build provenance, login output and discovery-file permissions (#85–#89).

## Important: mount your workspace for Docker file tools

Docker file tools require an explicitly mounted host directory at `/workspace` (or a deliberately configured `MCP_ALLOWED_ROOTS`). The old default Desktop/Documents/Downloads directories inside the container were not persistent host folders. **Without the mount, default filesystem access is disabled (fail closed), and `mcptoai doctor` warns that the workspace is missing.** The `/data` volume is separate: it persists configuration and pairing, not your working files.

```sh
mkdir -p "$HOME/mcptoai-workspace"
docker run -it --rm \
  -v mcptoai-data:/data \
  -v "$HOME/mcptoai-workspace:/workspace" \
  ghcr.io/mcptoai/mcptoai:0.3.1 login

docker run --rm \
  -v mcptoai-data:/data \
  -v "$HOME/mcptoai-workspace:/workspace" \
  ghcr.io/mcptoai/mcptoai:0.3.1 doctor

docker run -d --name mcptoai --restart unless-stopped \
  -v mcptoai-data:/data \
  -v "$HOME/mcptoai-workspace:/workspace" \
  ghcr.io/mcptoai/mcptoai:0.3.1
```

Use an existing trusted host directory instead of `$HOME/mcptoai-workspace` if preferred. Mount only directories you intend the agent to access. Docker commands above are **for the upcoming 0.3.1 release**; use the published 0.3.0 instructions until 0.3.1 artifacts exist.

Other changes: single configured-provider-key fallback for model discovery; missing key is informational; Docker image embeds source commit in `--version`; Docker login reports device name rather than account subject and shows container instructions; MCP discovery snapshots are atomically replaced with mode `0600`.

Release order: public source export and merge → matching Core/public tags → signed PyPI/GHCR/GitHub Release. Desktop Latest is unchanged.
