from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def test_preview_setting_is_wired_to_existing_local_ipc():
    html=(ROOT/'desktop/src/index.html').read_text(encoding='utf-8')
    js=(ROOT/'desktop/src/renderer.js').read_text(encoding='utf-8')
    assert 'id="toggleChatgptPreview"' in html
    assert "window.mcp.siwcPreview('status')" in js
    assert "window.mcp.siwcPreview(enabled?'off':'on')" in js
    assert "button.setAttribute('aria-pressed',String(enabled))" in js

def test_platform_neutral_account_and_mac_only_permissions():
    html=(ROOT/'desktop/src/index.html').read_text(encoding='utf-8')
    js=(ROOT/'desktop/src/renderer.js').read_text(encoding='utf-8')
    assert 'id="macPermissionsSettingsRow"' in html
    assert "info.platform!=='darwin'" in js
    assert "$('#macPermissionsSettingsRow').classList.add('hidden')" in js
    assert 'This device is connected to your MCPtoAI web account.' in js
    assert 'This Mac is connected' not in js
