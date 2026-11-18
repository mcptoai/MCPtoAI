import asyncio
from mcptoai_agent.context_layers import ContextLayers
from mcptoai_agent.context_summary import IncrementalSummarizer


class FakeProvider:
    name = 'fake'
    model = 'selected-model'
    context_window_tokens = 4096
    def __init__(self):
        self.calls = 0
    async def complete(self, system, messages, tools):
        self.calls += 1
        return type('Response', (), {'text': 'Older discussion (unverified)'})()


def test_summary_only_after_budget_overflow_and_incremental():
    async def run():
        provider = FakeProvider()
        summarizer = IncrementalSummarizer(ContextLayers())
        small = [{'role': 'user', 'content': 'hello'}]
        assert not await summarizer.after_turn(provider, 'system', small, [])
        assert provider.calls == 0
        history = [{'role': 'user', 'content': 'old ' * 3000},
                   {'role': 'assistant', 'content': 'response'},
                   {'role': 'user', 'content': 'latest'}]
        assert await summarizer.after_turn(provider, 'system', history, [])
        assert provider.calls == 1
        assert not await summarizer.after_turn(provider, 'system', history, [])
        assert provider.calls == 1
        assert summarizer.layers.l3[0]['verified'] is False
        assert summarizer.metrics[0].model == 'selected-model'
        assert summarizer.metrics[0].estimated_cost_usd is None
    asyncio.run(run())


def test_explicit_summarizer_model_and_verified_rate_override():
    async def run():
        chat = FakeProvider()
        summary = FakeProvider()
        summary.model = 'explicit-summary-model'
        layers = ContextLayers()
        worker = IncrementalSummarizer(layers)
        history = [{'role': 'user', 'content': 'old ' * 3000},
                   {'role': 'assistant', 'content': 'previous answer'},
                   {'role': 'user', 'content': 'new question'}]
        assert await worker.after_turn(chat, 'system', history, [], summary_provider=summary,
            pricing={'input_usd_per_million': '1.25', 'output_usd_per_million': '4.00'})
        assert chat.calls == 0 and summary.calls == 1
        assert worker.metrics[0].model == 'explicit-summary-model'
        assert worker.metrics[0].estimated_cost_usd is not None
    asyncio.run(run())
