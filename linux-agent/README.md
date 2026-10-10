# MCPtoAI for Linux

MCPtoAI connects a Linux machine to AI so you can work with it from the MCPtoAI web app, your phone, or directly from a terminal over SSH.

Your AI provider credentials stay on the machine. Filesystem access is workspace-scoped, terminal execution is disabled by default, and actions that require approval remain under your control.

## What you can do

- **Remote chat** — use your Linux machine from `app.mcptoai.com` or a phone.
- **Choose your AI provider and model** — configure provider keys locally and switch models without reinstalling the agent.
- **Use MCP servers** — connect remote HTTPS Streamable HTTP MCP servers or local stdio MCP servers.
- **Work with files** — expose a controlled workspace rather than your entire filesystem.
- **Run long jobs** — follow builds, training jobs, scripts and other background work across chat sessions.
- **Use the terminal** — `mcptoai chat` works over SSH without opening a browser.
- **Run continuously** — install a systemd user service, or run MCPtoAI in Docker.

## Requirements

For a normal Python installation:

- Linux
- Python 3.11 or newer
- a logged-in MCPtoAI account
- an API key for the AI provider you want to use, unless that provider does not require one

Docker does not require a host Python installation.

## Install

### pipx — recommended

```bash
pipx install mcptoai
```

`pipx` keeps the CLI isolated from system Python packages while still making the `mcptoai` command available globally for your user.

### pip

```bash
python3 -m pip install mcptoai
```

### Check the installation

```bash
mcptoai --version
mcptoai --help
```

## 60-second quick start

Pair the machine:

```bash
mcptoai login
```

Save a provider API key. The key is requested through a hidden prompt and is not passed as a command-line argument:


```bash
mcptoai keys set anthropic
```

Optional: keep conversation history only on this Linux device:

```bash
mcptoai history local
```

Use `mcptoai history status` to check the current setting, or `mcptoai history cloud` to use MCPtoAI Cloud for cross-device history.

See available models and choose one:

```bash
mcptoai models anthropic
mcptoai use anthropic <model-id>
```

Keep the device connected in the background:

```bash
mcptoai service install
```

Verify the setup:

```bash
mcptoai doctor
mcptoai status
```

Then open `https://app.mcptoai.com` and select this Linux device.

## Command reference

The CLI has built-in documentation. Start with:

```bash
mcptoai --help
```

Every major command also has its own help page:

```bash
mcptoai login --help
mcptoai keys --help
mcptoai models --help
mcptoai use --help
mcptoai workspace --help
mcptoai mcp --help
mcptoai shell --help
mcptoai jobs --help
mcptoai chat --help
mcptoai service --help
mcptoai update --help
mcptoai reset --help
```

### Account and diagnostics

```bash
mcptoai login       # pair this machine
mcptoai logout      # disconnect it without deleting local keys/settings
mcptoai status      # current pairing/provider/vault/service/job state
mcptoai doctor      # installation and configuration checks
```

`mcptoai doctor` returns a non-zero exit status when an important check fails, so it can also be used in scripts and deployment checks.

### Provider keys

```bash
mcptoai keys list
mcptoai keys set openai
mcptoai keys set anthropic
mcptoai keys remove openai
```

Provider keys are deliberately **not accepted as command-line arguments**. This reduces accidental exposure through shell history and process listings.

### Models

```bash
mcptoai models
mcptoai models openai
mcptoai use openai <model-id>
```

`mcptoai models` without a provider uses the currently selected provider.

### Filesystem workspace

Show the current scope:

```bash
mcptoai workspace show
```

Restrict MCPtoAI file tools to one directory:

```bash
mcptoai workspace set ~/projects/my-app
```

Return to the default Desktop/Documents/Downloads scope:

```bash
mcptoai workspace reset
```

Changing the workspace restarts the background service if it is running.

## MCP servers

List configured MCP servers:

```bash
mcptoai mcp list
```

### Remote HTTPS MCP

Add a Streamable HTTP MCP endpoint:

```bash
mcptoai mcp add-http Cloudflare https://mcp.cloudflare.com/mcp
```

Remote MCP URLs must use HTTPS. If the service uses OAuth, MCPtoAI starts the authorization flow during tool discovery.

### Local stdio MCP

```bash
mcptoai mcp add-stdio my-tools /path/to/server --arg value
```

A local stdio MCP server executes code on this machine with your Linux user permissions. For that reason it must be added locally and requires confirmation.

Remove a configured server using the id shown by `mcptoai mcp list`:

```bash
mcptoai mcp remove mcp-0123456789ab
```

## Terminal command permission

Terminal execution and long-running jobs are controlled by a local permission:

```bash
mcptoai shell status
mcptoai shell on
mcptoai shell off
```

Important security properties:

- terminal execution is **off by default**;
- it can only be enabled locally on the Linux machine;
- a remote web client cannot turn it on;
- sensitive tool calls can still require explicit approval.

## Long-running jobs

```bash
mcptoai jobs list
mcptoai jobs show job-1234abcd
mcptoai jobs logs job-1234abcd
mcptoai jobs logs job-1234abcd --follow
mcptoai jobs stop job-1234abcd
```

Jobs are kept independently of one model response, so a later chat/model session can still inspect their state.

## Terminal chat

Start a chat directly over SSH or a local terminal:

```bash
mcptoai chat
```

Override the configured model for that terminal session:

```bash
mcptoai chat --provider openai --model <model-id>
```

Inside terminal chat:

```text
/help
/model <model-id>
/provider <provider> <model-id>
/new
/jobs
/exit
```

When a tool needs approval, the terminal asks interactively. Non-interactive stdin does not silently approve tool calls.

## Background service

Install the systemd user service after pairing:

```bash
mcptoai service install
```

Manage it with:

```bash
mcptoai service status
mcptoai service restart
mcptoai service stop
mcptoai service start
mcptoai service logs
mcptoai service logs --follow
mcptoai service uninstall
```

For servers that must remain reachable after you log out, `mcptoai doctor` also checks whether systemd user lingering is enabled and shows the relevant `loginctl` command when needed.

For foreground/debug operation:

```bash
mcptoai connect
```

## Updating MCPtoAI

Check whether a newer CLI release is available on PyPI without changing anything:

```bash
mcptoai update --check
```

Install the latest release:

```bash
mcptoai update
```

MCPtoAI detects how the CLI was installed:

- **pipx** installations update the `mcptoai` pipx environment from the official public PyPI index;
- **pip / virtual environment** installations use the Python interpreter running MCPtoAI and the official public PyPI index;
- if the MCPtoAI systemd user service was already running, it is restarted only after a successful update;
- if the upgrade fails, the running background service is left alone;
- **Docker** installations are not modified from inside the container. Pull the newer image and recreate/restart the container instead.

You can always confirm the installed version with:

```bash
mcptoai --version
```


## Docker

Pair using a persistent configuration volume:

```bash
docker run -it --rm \
  -v mcptoai:/home/mcptoai/.config \
  ghcr.io/mcptoai/mcptoai login
```

Then run continuously:

```bash
docker run -d \
  --name mcptoai \
  --restart unless-stopped \
  -v mcptoai:/home/mcptoai/.config \
  ghcr.io/mcptoai/mcptoai
```

Inside Docker, the container restart policy replaces the systemd user service.

### Updating Docker

Docker containers are immutable, so `mcptoai update` does not modify a running container. Pull the new image and recreate the container while keeping the same persistent config volume:

```bash
docker pull ghcr.io/mcptoai/mcptoai:latest
docker stop mcptoai
docker rm mcptoai
docker run -d \
  --name mcptoai \
  --restart unless-stopped \
  -v mcptoai:/home/mcptoai/.config \
  ghcr.io/mcptoai/mcptoai:latest
```

The `mcptoai` named volume keeps pairing, provider credentials and local configuration across container replacement. Release images are also tagged with their CLI version, for example `ghcr.io/mcptoai/mcptoai:0.1.16`.

## Troubleshooting

Start with:

```bash
mcptoai status
mcptoai doctor
```

Check the background service:

```bash
mcptoai service status
mcptoai service logs -n 100
```

Follow live logs:

```bash
mcptoai service logs --follow
```

For a Python traceback while debugging a CLI failure:

```bash
MCPTOAI_DEBUG=1 mcptoai <command>
```

If an AI provider is not ready:

```bash
mcptoai keys list
mcptoai models <provider>
mcptoai use <provider> <model-id>
```

If a remote MCP integration is not available, inspect configured servers with:

```bash
mcptoai mcp list
```

## Security model

MCPtoAI is designed so that connecting the machine does not automatically grant unrestricted execution access.

- Provider API keys are stored locally in the MCPtoAI vault.
- Keys are not accepted as normal CLI arguments.
- File tools are constrained to the configured workspace.
- Terminal execution is disabled by default and can only be enabled locally.
- Local stdio MCP servers require local confirmation because they execute code on the machine.
- Remote MCP endpoints must use HTTPS; OAuth integrations can authorize through their provider.
- Sensitive tool actions can require approval before execution.
- The device establishes an outbound connection; you do not need to expose an inbound MCPtoAI port on the server.

See the security documentation for the current threat model and implementation details: `https://mcptoai.com/security/`.

## Disconnect, uninstall and reset

Disconnect the device but keep local configuration:

```bash
mcptoai logout
```

Remove only the background service:

```bash
mcptoai service uninstall
```

Completely remove the local MCPtoAI configuration, provider credentials, MCP configuration, pairing and service:

```bash
mcptoai reset
```

`mcptoai reset` is destructive for **local MCPtoAI data on this machine**. It does not delete your MCPtoAI account or cloud-side account data.

To remove the Python package afterwards:

```bash
pipx uninstall mcptoai
```

or, if installed with pip:

```bash
python3 -m pip uninstall mcptoai
```

## License

The MCPtoAI Linux CLI/agent is available under the MIT License. The hosted MCPtoAI service, backend, relay, web application and trademarks are separate from the MIT-licensed client code.

## Links

- Product: `https://mcptoai.com/`
- Web app: `https://app.mcptoai.com/`
- How it works: `https://mcptoai.com/how-it-works/`
- Security: `https://mcptoai.com/security/`
- Privacy: `https://mcptoai.com/privacy/`
- Terms: `https://mcptoai.com/terms/`

© BKTY LTD
