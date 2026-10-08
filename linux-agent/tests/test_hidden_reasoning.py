from mcptoai_linux.providers.base import strip_hidden_reasoning

def test_closed_think_block_removed():
    assert strip_hidden_reasoning("<think>secret reasoning</think>\nHello!") == "Hello!"

def test_multiple_think_blocks_removed():
    assert strip_hidden_reasoning("<think>a</think>Answer<think>b</think> done") == "Answer done"

def test_unclosed_think_fails_closed():
    assert strip_hidden_reasoning("Visible\n<think>secret") == "Visible"

def test_normal_answer_unchanged():
    assert strip_hidden_reasoning("Normal answer") == "Normal answer"
