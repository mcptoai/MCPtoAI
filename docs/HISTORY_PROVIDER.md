# Conversation History Provider Architecture

MCPtoAI treats conversation persistence as a separate subsystem from device execution, relay routing, authentication, entitlements, and application updates.

## Provider contract

The Device Agent exposes one internal `HistoryProvider` contract:

- `list_chats(archived=False)`
- `get_chat(chat_id)`
- `create_chat(title, provider, model)`
- `add_message(chat_id, role, content, model, tool_name, tool_data)`
- `update_chat(chat_id, title/is_pinned/is_archived)`
- `delete_chat(chat_id)`

The current Desktop IPC keeps its existing action names for compatibility. Storage selection happens behind the provider boundary.

## Current providers

### MCPtoAIHistoryProvider

Uses the managed MCPtoAI history API. This preserves the behaviour of existing releases and remains the default while the storage selector is introduced.

### LocalHistoryProvider

Stores history in a local SQLite database under the MCPtoAI user configuration directory. The database is created with user-only permissions where the platform supports POSIX file modes.

Local history does not change device pairing, relay routing, local tool permissions, provider credential storage, or official application updates.

## Planned provider: RemoteHistoryProvider

The future **My own server** option will implement the same provider contract through a documented HTTPS protocol.

A history node is intentionally **not** an MCPtoAI backend replacement. It does not receive authority over:

- application updates;
- device registration;
- local execution permissions;
- subscription entitlements;
- relay routing.

### Proposed protocol shape

The wire format is not frozen yet, but the resource model should remain close to:

```text
GET    /v1/chats?archived=0
POST   /v1/chats
GET    /v1/chats/{id}
PATCH  /v1/chats/{id}
DELETE /v1/chats/{id}
POST   /v1/chats/{id}/messages
```

Authentication should use a scoped bearer credential or organisation-issued token that grants history access only.

## Enterprise direction

A customer-hosted history node can later become a paid enterprise capability with controls such as:

- SSO integration;
- organisation/user mapping;
- configurable audit retention;
- data-residency deployment choices;
- backup and retention policies;
- administrator policy controls;
- optional encryption/key-management integration.

These enterprise features remain separate from the signed Desktop update channel. Even when history is customer-hosted, official MCPtoAI builds continue to use MCPtoAI-controlled signed update metadata and release artefacts.

## Security requirements

1. History storage selection must never grant additional tool permissions.
2. A history server must never be able to change the Desktop update feed.
3. Remote history credentials must be scoped to history operations only.
4. Tool outputs may contain sensitive data and must be treated as conversation data.
5. Attachments and binary artefacts need explicit retention and size rules before remote storage is enabled.
6. The protocol should support future client-side encryption without breaking resource identity or sync ordering.
