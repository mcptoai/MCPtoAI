"""Deterministic canary matrix; no real credentials are used."""
import base64
import json
import random
from urllib.parse import quote
import pytest

from mcptoai_agent.activity_events import make_event
from mcptoai_agent.activity_redaction import safe_target, safe_summary, HIDDEN

def test_hundreds_of_encoded_canaries_never_enter_event_json():
    rng = random.Random(2909)
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    for i in range(400):
        nonce = "".join(rng.choice(alphabet) for _ in range(36))
        secret = "sk-" + nonce
        variants = (
            secret,
            base64.b64encode(secret.encode()).decode(),
            quote(secret, safe=""),
            "sk-" + "\u200b".join(nonce[j:j+4] for j in range(0, len(nonce), 4)),
        )
        for variant in variants:
            for kind, target in (
                ("command", f'curl -H "Authorization: Bearer {variant}" https://example.com'),
                ("command", f'API_KEY={variant} git status'),
                ("command", f'echo "{variant}" | base64 -d'),
                ("url", f'https://user:{variant}@example.com/path?token={variant}'),
                ("mcp", "third_party"),
                ("other", variant),
            ):
                display = safe_target(kind, target, mcp_tool="call_tool")
                e = make_event(session_id="s1", turn_id="t1", tool_name="tool1",
                               phase="started", target_type=kind if kind != "other" else "other",
                               target_display=display, summary=safe_summary("started"))
                blob = json.dumps(e.payload(), ensure_ascii=False)
                assert secret not in blob
                assert variant not in blob
                assert nonce not in blob
                assert base64.b64encode(secret.encode()).decode() not in blob
                assert quote(secret, safe="") not in blob

@pytest.mark.parametrize("kind,value", [
    ("other", "private"), ("application", "sk-abcdefghijk"),
    ("mcp", "sk-abcdefghijk"),
])
def test_unknown_or_untrusted_labels_hidden(kind, value):
    assert safe_target(kind, value, mcp_tool="list_tools").value == HIDDEN
