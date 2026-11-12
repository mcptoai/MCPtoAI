import pytest
from mcptoai_agent.activity_events import make_event, validate_payload, ActivityEvent
from mcptoai_agent.activity_redaction import SafeDisplay, safe_target, safe_summary, hidden

def event(**kwargs):
    return make_event(session_id="sid1", turn_id="turn1", tool_name="run_command", phase="started", **kwargs)

def test_metadata_only():
    p = event().payload()
    assert "output" not in p and "arguments" not in p
    assert p["target_display"] == "[CONTENT HIDDEN]"

@pytest.mark.parametrize("field", ["output", "stdout", "stderr", "arguments", "file_content", "artifact_bytes", "command_line", "traceback"])
def test_reject_content_fields(field):
    p = event().payload()
    p[field] = "private content"
    with pytest.raises(ValueError):
        validate_payload(p)

def test_wire_validation_does_not_trust_display_strings():
    p = event().payload()
    p["target_display"] = "sk-abcdefghij"
    p["summary"] = "private data"
    restored = validate_payload(p)
    assert restored.target_display.value == "[CONTENT HIDDEN]"
    assert restored.summary.value == "Tool started"

def test_safe_display_is_minted_only():
    with pytest.raises(TypeError):
        SafeDisplay("sk-abcdefghij")
    with pytest.raises(TypeError):
        event(target_display="plain string")
    with pytest.raises(TypeError):
        event(summary="plain string")
    assert event(target_display=safe_target("command", "git status"), summary=safe_summary("completed")).target_display.value == "git status [arguments hidden]"

@pytest.mark.parametrize("phase", ["unknown", "success", "waiting"])
def test_invalid_phase(phase):
    with pytest.raises(ValueError):
        validate_payload(event().payload() | {"phase": phase})

def test_bad_identifiers_and_duration():
    with pytest.raises(ValueError):
        make_event(session_id="", turn_id="turn1", tool_name="run_command", phase="started")
    with pytest.raises(ValueError):
        event(duration_ms=-1)

def test_activity_id_not_transport_sequence():
    a = event()
    assert "event_seq" not in a.payload() and "event_epoch" not in a.payload()
    assert a.activity_id != event().activity_id

def test_permission_metadata_no_authorization_effect():
    assert event(permission_decision="denied").phase == "started"

def test_unknown_target_defaults_hidden():
    assert safe_target("unknown", "sk-abcdefghij").value == "[CONTENT HIDDEN]"
    assert safe_summary("anything secret").value == "[CONTENT HIDDEN]"

def test_provider_model_safe_identifiers_and_wire_contract():
    p = event(provider='openai', model='gpt-6.1-sol').payload()
    assert p['provider'] == 'openai' and p['model'] == 'gpt-6.1-sol'
    assert validate_payload(p).provider == 'openai'
    for unsafe in ('sk-secret', 'model/name', 'model name', 'x'*129, 'x\nprivate'):
        with pytest.raises(ValueError):
            event(provider='openai', model=unsafe)


def test_recorder_redacts_unsafe_model_identity():
    from mcptoai_agent.activity_recorder import ActivityRecorder
    r=ActivityRecorder('session',enabled=False,provider='openai',model='sk-SECRET123')
    assert r.model.startswith('h-')
    assert 'SECRET' not in r.model
