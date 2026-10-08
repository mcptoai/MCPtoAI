# MCPtoAI — Device Agent

The agent runs on the user's own computer. The user's AI-provider API key remains in the supported operating-system credential store and the model/agent loop runs locally. MCPtoAI's backend provides identity, device registration and relay routing; it does not need the user's AI-provider API key.

## User flow

1. Install/open MCPtoAI Desktop.
2. Add an Anthropic/OpenAI API key; it is stored in Keychain/Credential Manager.
3. Sign in to MCPtoAI. The app uses MCPtoAI's Auth0 Native application and Device Authorization Flow; the user does **not** create an Auth0 app.
4. Approve the requested macOS/Windows permissions for the tools they want to use.
5. MCPtoAI Desktop registers the device and opens an outbound WSS connection to `api.mcptoai.com`. No inbound port, ngrok, Cloudflare Tunnel or static IP is required on the user's computer.

## Development commands

```bash
cd device-agent
source .venv/bin/activate
cp .env.example .env
# During development, set the MCPtoAI Auth0 tenant + Native Application Client ID in .env.
python -m mcptoai_agent doctor
python -m mcptoai_agent set-key anthropic
python -m mcptoai_agent tools
python -m mcptoai_agent chat
python -m mcptoai_agent login
python -m mcptoai_agent connect
```

## MCPtoAI Auth0 configuration (product owner only)

MCPtoAI needs one Auth0 API with Identifier `https://api.mcptoai.com` and RS256 signing, plus a **Native** application for MCPtoAI Desktop with Device Code grant enabled. The Native application's Client ID is public application configuration; no Client Secret is embedded in MCPtoAI Desktop. Refresh tokens and provider keys are stored in the supported operating-system credential store.

## Security boundaries

- No provider API key is sent to or stored by the MCPtoAI backend.
- The desktop agent makes the outbound relay connection; users do not expose an inbound server.
- Tool permissions are enforced locally. Dangerous operations require approval.
- Device connections are authenticated with device-specific signing keys. MCPtoAI does not currently provide end-to-end payload encryption; relay traffic is protected in transit with TLS.
