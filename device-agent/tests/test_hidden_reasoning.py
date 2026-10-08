from mcptoai_agent.providers.base import strip_hidden_reasoning

def test_strips_complete_think_block():
    assert strip_hidden_reasoning("<think>secret reasoning</think>\nHello!") == "Hello!"

def test_strips_multiline_and_case_insensitive_blocks():
    text="prefix\n<THINK>one\ntwo</THINK>\nanswer"
    assert strip_hidden_reasoning(text) == "prefix\n\nanswer"

def test_strips_multiple_think_blocks():
    text="<think>a</think>Answer<think>b</think> done"
    assert strip_hidden_reasoning(text) == "Answer done"

def test_unclosed_think_fails_closed():
    assert strip_hidden_reasoning("Visible\n<think>secret") == "Visible"

def test_normal_text_unchanged():
    assert strip_hidden_reasoning("Normal answer") == "Normal answer"
