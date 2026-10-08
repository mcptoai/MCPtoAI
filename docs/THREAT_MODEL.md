# MCPtoAI Threat Model

This document describes the security assumptions for the open Desktop and Device Agent clients. It intentionally does not document private hosted-service implementation details.

## Assets to protect

- local files and application data;
- provider API credentials and OAuth tokens;
- device identity and pairing material;
- screen, camera, and microphone data;
- tool outputs and conversation content;
- user-approved command execution boundaries.

## Trust boundaries

### Device Agent

The Device Agent is the final authority for local execution policy. It validates paths, local capabilities, approval requirements, and blocked privilege-escalation patterns before executing supported tools.

### Desktop UI

The Desktop application presents local state and approvals but is not a substitute for enforcement inside the Device Agent. Security-critical checks should be enforced again at the agent boundary where practical.

### Hosted MCPtoAI service

The hosted service provides account/device coordination and relay functionality. It must not be considered trusted to override local safety controls.

### AI providers and MCP servers

AI providers and connected MCP servers are external systems. Their output is untrusted input. Tool requests derived from model output must still pass local policy.

### History providers

History storage is a separate data boundary. A `HistoryProvider` may be local, MCPtoAI-managed, or user-hosted. Changing history storage must not change tool permissions, device pairing, entitlement checks, or the official update source.

## Threat scenarios

### Hosted account compromise

An attacker who gains access to a user's hosted account may be able to request operations available to that account, but must not be able to silently enable capabilities that the user disabled locally or bypass approval requirements for sensitive tools.

### Relay compromise

A compromised relay must not be sufficient to grant new local capabilities. Requests arriving from the relay are still subject to local validation and policy.

### Malicious model output

Prompt injection or malicious model output may attempt to read files, run commands, or exfiltrate data. Tool requests are treated as untrusted until local policy allows them.

### Malicious MCP server

A connected MCP server may return hostile or misleading content. Adding local stdio MCP servers is particularly sensitive because they execute local code with the user's permissions.

### Local machine compromise

MCPtoAI cannot protect secrets or policy files from an attacker who already has equivalent or greater access to the user's operating-system account. The goal is to avoid creating an easier remote path to that access.

## Security invariants

1. Remote requests cannot grant themselves new locally-disabled capabilities.
2. Privilege escalation is not an intended feature of AI-driven shell execution.
3. Sensitive tool execution is approval-gated according to local policy.
4. Credentials are not stored in repository source or release packages.
5. History storage selection does not control application updates.
6. Official updates continue to come from MCPtoAI's signed release infrastructure.
7. The hosted service and client release pipeline remain separate trust domains.

## Future customer-hosted history

A future customer-hosted history node may support organisational controls such as SSO integration, audit retention, and data residency. Such a node is a storage/synchronisation component, not a replacement for the MCPtoAI signed update service or local execution policy.
