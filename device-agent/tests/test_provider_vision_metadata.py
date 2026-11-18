"""Model görsel yetenekleri ve Anthropic gönderim dönüşümü."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from mcptoai_agent.providers.anthropic_provider import AnthropicProvider
from mcptoai_agent.providers.evren_provider import EvrenProvider

def test_anthropic_claude_models_report_image():
    provider=object.__new__(AnthropicProvider)
    provider.client=SimpleNamespace(models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(id='claude-sonnet-5',display_name='Sonnet'),SimpleNamespace(id='other-model',display_name='Other')],has_more=False))))
    models=asyncio.run(provider.list_models())
    assert models[0]['modalities']==['text','image']
    assert models[1]['modalities']==['text']

def test_anthropic_image_is_sent_to_api():
    messages=AnthropicProvider._convert([{'role':'user','content':'Describe','images':[{'data_url':'data:image/png;base64,YWJj'}]}])
    assert messages[0]['content'][1]=={'type':'image','source':{'type':'base64','media_type':'image/png','data':'YWJj'}}

def test_anthropic_invalid_image_rejected():
    with pytest.raises(ValueError):
        AnthropicProvider._convert([{'role':'user','content':'test','images':[{'data_url':'file:///secret'}]}])

def test_evren_vision_chat_without_modalities():
    provider=object.__new__(EvrenProvider)
    provider._models_cache=[];provider._models_cache_at=0
    provider.client=SimpleNamespace(models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(id='vision',model_extra={'task':'vision_chat'}),SimpleNamespace(id='chat',model_extra={'task':'chat'})]))))
    models=asyncio.run(provider.list_models())
    assert models[0]['modalities']==['text','image']
    assert models[1]['modalities']==['text']

@pytest.mark.parametrize('model_id', ['claude-3-5-sonnet-20241022', 'claude-sonnet-4-5', 'claude-sonnet-5', 'claude-opus-4-1', 'claude-haiku-4-5'])
def test_claude_family_capabilities(model_id):
    from mcptoai_agent.providers.model_modalities import modalities_for_model
    assert modalities_for_model(model_id, provider='anthropic') == ['text', 'image']

def test_unknown_anthropic_model_does_not_claim_vision():
    from mcptoai_agent.providers.model_modalities import modalities_for_model
    assert modalities_for_model('unidentified-model', provider='anthropic') == ['text']

def test_openai_and_siwc_keep_reported_modalities():
    from mcptoai_agent.providers.model_modalities import modalities_for_model
    assert modalities_for_model('unknown', ['text', 'image']) == ['text', 'image']
    assert modalities_for_model('unknown', None) is None
