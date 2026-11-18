from types import SimpleNamespace
from mcptoai_agent.session_context import inherit_model_context
from mcptoai_agent.context_layers import ContextLayers
from mcptoai_agent.context_summary import IncrementalSummarizer
from mcptoai_agent.context_budget import resolve_budget
from mcptoai_agent.context_layers import select_layered


def session(model, text):
    layers = ContextLayers()
    layers.l0.append({'content': 'System priority'})
    layers.l1.append({'content': 'Verified observation', 'source': 'local tool', 'observed_at': '2026-11-16T10:00:00+00:00', 'verified': True})
    layers.l3.append({'content': 'Historical summary', 'verified': False})
    return SimpleNamespace(provider=SimpleNamespace(name='openai', model=model), history=[{'role': 'user', 'content': text}], context_layers=layers, context_summarizer=IncrementalSummarizer(layers))


def test_model_switch_retains_history_layers_and_recalculates_budget():
    old = session('small', 'previous question')
    new = session('large', '')
    new.provider.context_window_tokens = 32768
    assert inherit_model_context(new, {'sid:openai:small:keyA': old}, {'sid:openai:small:keyA': 5}, session_key='sid:openai:large:keyA', sid='sid', provider='openai', fingerprint='keyA')
    assert new.history == old.history and new.history is not old.history
    assert new.context_layers is old.context_layers
    assert new.context_summarizer is old.context_summarizer
    assert new.provider is not old.provider
    budget = resolve_budget(new.provider)
    assert budget.context_tokens == 32768
    prefix, kept, _ = select_layered('System', new.history, budget, new.context_layers)
    assert 'System priority' in prefix and 'Verified observation' in prefix
    assert kept == old.history


def test_no_cross_provider_or_credential_inheritance():
    old = session('small', 'private history')
    for provider, fingerprint in [('anthropic', 'keyA'), ('openai', 'keyB')]:
        new = session('large', 'clean')
        assert not inherit_model_context(new, {'sid:openai:small:keyA': old}, {}, session_key=f'sid:{provider}:large:{fingerprint}', sid='sid', provider=provider, fingerprint=fingerprint)
        assert new.history[0]['content'] == 'clean'


def test_latest_model_session_wins():
    first = session('one', 'old')
    latest = session('two', 'new')
    target = session('three', '')
    sessions = {'sid:openai:one:keyA': first, 'sid:openai:two:keyA': latest}
    assert inherit_model_context(target, sessions, {'sid:openai:one:keyA': 1, 'sid:openai:two:keyA': 9}, session_key='sid:openai:three:keyA', sid='sid', provider='openai', fingerprint='keyA')
    assert target.history[0]['content'] == 'new'
