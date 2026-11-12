from pathlib import Path


def test_capture_screen_instruction_and_result_contract():
    source = (Path(__file__).parents[1] / "mcptoai_agent" / "agent.py").read_text()
    assert "A successful capture_screen call already sends its screenshot image" in source
    assert "Do not call send_artifact to deliver that same screenshot again" in source
    assert "already delivered to the user interface. Do not call send_artifact" in source
    assert 'call.name == "capture_screen" and not is_error' in source
    assert 'if not is_error and call.name == "send_artifact"' in source


def test_send_artifact_permission_not_changed():
    source = (Path(__file__).parents[1] / "mcptoai_agent" / "policy.py").read_text()
    assert '"send_artifact": Decision.CONFIRM' in source
