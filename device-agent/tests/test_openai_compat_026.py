"""OpenAI uyumluluk testleri."""
import json
import asyncio
import httpx
import pytest
from openai import AsyncOpenAI
from mcptoai_agent.providers.openai_compat import normalize_completion
from mcptoai_agent.providers.openai_provider import OpenAIProvider

def chunk(delta, finish=None):
    return 'data: '+json.dumps({'choices':[{'index':0,'delta':delta,'finish_reason':finish}]})+'\n\n'

def test_sse_text():
    result=normalize_completion(chunk({'content':'Hello ','reasoning_content':'private'})+chunk({'content':'world'},'stop')+'data: [DONE]\n')
    assert result.choices[0].message.content=='Hello world'
    assert 'private' not in result.choices[0].message.content

def test_sse_tools():
    body=chunk({'tool_calls':[{'index':0,'id':'call_1','function':{'name':'read_file','arguments':'{"path":'}}]})+chunk({'tool_calls':[{'index':0,'function':{'arguments':'"/tmp"}'}}]},'tool_calls')
    call=normalize_completion(body).choices[0].message.tool_calls[0]
    assert (call.id,call.function.name,json.loads(call.function.arguments))==('call_1','read_file',{'path':'/tmp'})

def test_json():
    data={'id':'x','object':'chat.completion','created':0,'model':'m','choices':[{'index':0,'message':{'role':'assistant','content':'ok'},'finish_reason':'stop'}]}
    assert normalize_completion(json.dumps(data),'text/plain').choices[0].message.content=='ok'

def test_bad_body_redacted():
    with pytest.raises(ValueError) as exc:
        normalize_completion('oops sk-VERYSECRET1234','text/plain')
    assert 'sk-VERYSECRET1234' not in str(exc.value)
    assert 'content-type=text/plain' in str(exc.value)

def test_http_stream_false():
    asyncio.run(_test_http_stream_false())

async def _test_http_stream_false():
    seen=[]
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,json={'id':'x','object':'chat.completion','created':0,'model':'m','choices':[{'index':0,'message':{'role':'assistant','content':'selam'},'finish_reason':'stop'}]})
    p=OpenAIProvider('test-key','m','https://example.invalid/v1')
    await p.client.close()
    p.client=AsyncOpenAI(api_key='test-key',base_url='https://example.invalid/v1',http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        assert (await p.complete('system',[{'role':'user','content':'selam'}],[])).text=='selam'
        assert seen[0]['stream'] is False
    finally:
        await p.client.close()
