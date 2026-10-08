from __future__ import annotations

import json


def test_static_oauth_secret_stays_out_of_mcp_config(monkeypatch, tmp_path):
    from mcptoai_agent import mcp_config

    vault = {}

    def store_map(server_id, kind, values):
        keys = []
        for key, value in (values or {}).items():
            vault[(server_id, kind, str(key))] = str(value)
            keys.append(str(key))
        return keys

    def load_map(server_id, kind, keys):
        return {
            str(key): vault[(server_id, kind, str(key))]
            for key in keys
            if (server_id, kind, str(key)) in vault
        }

    def delete_map(server_id, kind, keys):
        for key in keys:
            vault.pop((server_id, kind, str(key)), None)

    monkeypatch.setattr(mcp_config, "PATH", tmp_path / "mcp-tools.json")
    monkeypatch.setattr(mcp_config, "store_map", store_map)
    monkeypatch.setattr(mcp_config, "load_map", load_map)
    monkeypatch.setattr(mcp_config, "delete_map", delete_map)
    monkeypatch.setattr(mcp_config, "validate_remote_mcp_url", lambda value: value)

    item = mcp_config.add_server(
        "Google Drive",
        transport="streamable-http",
        url="https://drivemcp.googleapis.com/mcp/v1",
        oauth={
            "client_id": "client-id.apps.googleusercontent.com",
            "client_secret": "top-secret-value",
            "token_endpoint_auth_method": "client_secret_post",
        },
    )

    raw_text = mcp_config.PATH.read_text(encoding="utf-8")
    assert "top-secret-value" not in raw_text
    raw = json.loads(raw_text)
    saved = raw["servers"][0]
    assert saved["oauth_client_id"] == "client-id.apps.googleusercontent.com"
    assert saved["oauth_secret_keys"] == ["client_secret"]

    loaded = mcp_config.custom_servers()[0]
    assert loaded["oauth"]["client_secret"] == "top-secret-value"
    public = mcp_config.state({item["id"]: ["drive.search_files"]})["servers"][1]
    assert public["oauth_configured"] is True
    assert "oauth" not in public
    assert "client_secret" not in json.dumps(public)

    # Avoid touching the real OAuth token store in this unit test.
    monkeypatch.setattr("mcptoai_agent.mcp_oauth.delete_oauth_storage", lambda _sid: None)
    assert mcp_config.remove_server(item["id"]) is True
    assert not any(k[0] == item["id"] for k in vault)


def test_google_static_oauth_metadata_uses_confidential_client():
    from mcptoai_agent.mcp_oauth import oauth_metadata_for

    metadata = oauth_metadata_for(
        {
            "oauth": {
                "client_id": "client-id.apps.googleusercontent.com",
                "client_secret": "secret",
                "token_endpoint_auth_method": "client_secret_post",
            }
        }
    )
    assert metadata.token_endpoint_auth_method == "client_secret_post"
    assert str(metadata.redirect_uris[0]) == "https://app.mcptoai.com/api/mcp/oauth/callback"


def test_oauth_client_secret_is_vault_only(monkeypatch, tmp_path):
    import asyncio
    from mcp.shared.auth import OAuthClientInformationFull
    from mcptoai_agent import mcp_oauth

    vault = {}

    async def fake_amutate(fn):
        fn(vault)
        return dict(vault)

    monkeypatch.setattr(mcp_oauth, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(mcp_oauth, "amutate", fake_amutate)
    monkeypatch.setattr(mcp_oauth, "get_secret", lambda name: vault.get(name))

    storage = mcp_oauth.FileTokenStorage("mcp-google-test")
    info = OAuthClientInformationFull(
        client_id="client.apps.googleusercontent.com",
        client_secret="vault-only-secret",
        redirect_uris=[mcp_oauth.OAUTH_CALLBACK_URL],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        client_name="MCPtoAI",
    )
    asyncio.run(storage.set_client_info(info))

    disk = storage.path.read_text(encoding="utf-8")
    assert "vault-only-secret" not in disk
    assert vault[storage.client_secret_key] == "vault-only-secret"
    restored = asyncio.run(storage.get_client_info())
    assert restored.client_secret == "vault-only-secret"



def test_generic_oauth_has_no_google_drive_broker():
    from mcptoai_agent import mcp_oauth
    assert not hasattr(mcp_oauth, "GOOGLE_DRIVE_BROKER_URL")
    assert not hasattr(mcp_oauth, "BrokeredGoogleOAuthClientProvider")
