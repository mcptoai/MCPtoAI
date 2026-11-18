from types import SimpleNamespace
import pytest
from mcptoai_agent.context_budget import resolve_budget, assemble, estimate_tokens


def test_provider_limits_and_unknown_fallback():
    unknown = resolve_budget(SimpleNamespace(model='unknown'), tool_count=2)
    assert unknown.context_tokens == 131072 and unknown.source == 'conservative_unknown'
    known = resolve_budget(SimpleNamespace(context_window_tokens=32768, max_input_tokens=12000), tool_count=2)
    assert known.context_tokens == 12000 and known.input_tokens < 12000
    assert resolve_budget(SimpleNamespace(context_window_tokens='999999')).context_tokens == 131072


def test_canonical_history_not_modified_and_deterministic():
    budget = resolve_budget(SimpleNamespace())
    history = [{'role':'user','content':'old'*90000}, {'role':'assistant','content':'old response'*2000},
               {'role':'user','content':'current question'}]
    original = [dict(m) for m in history]
    a = assemble('system', history, budget)
    assert a == assemble('system', history, budget)
    assert a[2] is True and a[1][-1]['content'] == 'current question'
    assert 'omitted' in a[0]
    assert history == original


def test_small_history_verbatim():
    history=[{'role':'user','content':'hello'}, {'role':'assistant','content':'hi'}]
    assert assemble('system', history, resolve_budget(SimpleNamespace())) == ('system',history,False)


def test_oversized_latest_item_fails_not_fabricates():
    with pytest.raises(ValueError,match='Latest conversation item'):
        assemble('system',[{'role':'user','content':'x'*300000}],resolve_budget(SimpleNamespace()))


def test_tool_result_stays_with_call():
    budget=resolve_budget(SimpleNamespace())
    history=[{'role':'user','content':'old'*4000},
             {'role':'assistant','content':'', 'tool_calls':[{'id':'x','name':'read_file'}]},
             {'role':'tool','tool_call_id':'x','name':'read_file','content':'observed'},
             {'role':'assistant','content':'last observed, not current'}]
    _, messages, _ = assemble('system',history,budget)
    assert any(m.get('role')=='tool' for m in messages) == any(m.get('tool_calls') for m in messages)


def test_many_tools_cannot_starve_system_prompt():
    budget = resolve_budget(SimpleNamespace(model='unknown'), tool_count=200)
    assert budget.tool_reserve <= budget.context_tokens // 8
    system = 'Important system instruction. ' * 110
    _, messages, truncated = assemble(system, [{'role': 'user', 'content': 'hello'}], budget)
    assert not truncated and messages[-1]['content'] == 'hello'


def test_unknown_provider_does_not_have_verified_limit():
    # The conservative 128k estimate is not a verified provider guarantee.
    assert resolve_budget(SimpleNamespace(model='gpt-5')).source == 'conservative_unknown'




def test_unknown_model_bounded_and_visible():
    budget = resolve_budget(SimpleNamespace(name='openai'))
    assert budget.context_tokens == 131072
    prompt, messages, truncated = assemble('system', [
        {'role':'user','content':'old' * 90000},
        {'role':'user','content':'recent'},
    ], budget)
    assert truncated and messages[-1]['content'] == 'recent'
    assert 'older conversation entries were omitted' in prompt


def test_context_exceeded_retries_once():
    import asyncio
    from mcptoai_agent.context_budget import complete_with_context_retry
    class Provider:
        name = 'openai'
        context_window_tokens = 32768
        def __init__(self): self.calls = []
        async def complete(self, system, messages, tools):
            self.calls.append(messages)
            if len(self.calls) == 1:
                raise ValueError('context length exceeded')
            return 'ok'
    provider = Provider()
    history = [{'role':'user','content':'old' * 12000}, {'role':'user','content':'recent'}]
    result, truncated = asyncio.run(complete_with_context_retry(provider,'system',history,[]))
    assert result == 'ok' and truncated and len(provider.calls) == 2
    assert len(provider.calls[1]) < len(provider.calls[0])


def test_context_exceeded_only_one_retry_and_clear_error():
    import asyncio
    from mcptoai_agent.context_budget import complete_with_context_retry
    class Provider:
        context_window_tokens = 32768
        calls = 0
        async def complete(self, system, messages, tools):
            self.calls += 1
            raise ValueError('context length exceeded')
    provider = Provider()
    with pytest.raises(RuntimeError, match='context_budget_exceeded'):
        asyncio.run(complete_with_context_retry(provider,'system',[{'role':'user','content':'hello'}],[]))
    assert provider.calls == 2


def test_protected_context_overflow_is_typed_user_error():
    import asyncio
    import pytest
    from mcptoai_agent.context_errors import ContextBudgetError, friendly_context_error
    from mcptoai_agent.context_budget import complete_with_context_retry
    from mcptoai_agent.context_layers import ContextLayers
    class Provider:
        name = 'openai'
        context_window_tokens = 4096
        async def complete(self, *args):
            raise AssertionError('provider must not be called')
    with pytest.raises(ContextBudgetError, match='context_budget_exceeded'):
        asyncio.run(complete_with_context_retry(Provider(), 'system', [{'role':'user','content':'hello'}], [], layers=ContextLayers(l0=[{'content':'x'*10000}])))
    for language in ('en','tr','de','fr','es','it','pt'):
        assert friendly_context_error(language) and 'context_budget_exceeded' not in friendly_context_error(language)
