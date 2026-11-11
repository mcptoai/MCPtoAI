import json
import pytest
from mcptoai_agent.providers.base import ToolCall, ToolSpec
from mcptoai_agent.providers.siwc_responses import request_payload, parse_events


def event(kind, **kwargs):
    return 'data: '+json.dumps({'type':kind,**kwargs})


def test_payload_roundtrip_and_no_server_storage():
    messages=[{'role':'user','content':'run'}, {'role':'assistant','content':'', 'tool_calls':[ToolCall('c1','read_file',{'path':'a'})]}, {'role':'tool','tool_call_id':'c1','content':'ok'}]
    payload=request_payload('test','system',messages,[ToolSpec('read_file','read',{'type':'object'})])
    assert payload['store'] is False and payload['stream'] is True
    assert payload['input'][1]['call_id']==payload['input'][2]['call_id']=='c1'
    assert payload['tools'][0]['name']=='read_file'


def test_sse_text_and_tool_call():
    lines=[event('response.output_text.delta',delta='Hello'),event('response.output_item.done',item={'type':'function_call','call_id':'c1','name':'read_file','arguments':'{"path":"a"}'}),event('response.completed')]
    result=parse_events(lines)
    assert result.text=='Hello' and result.tool_calls[0].arguments=={'path':'a'}


@pytest.mark.parametrize('lines', [[],[event('response.failed')],[event('response.incomplete')],[event('response.output_text.delta',delta='partial')],['data: invalid']])
def test_incomplete_or_invalid_stream_rejected(lines):
    with pytest.raises((RuntimeError,ValueError)):
        parse_events(lines)


def test_images_fail_closed():
    with pytest.raises(ValueError,match='image'):
        request_payload('m','s',[{'role':'user','content':'hi','images':[{'data_url':'data:image/png;base64,a'}]}],[])


def test_provider_uses_existing_provider_contract():
    import asyncio
    import httpx
    from mcptoai_agent.providers.siwc_provider import SIWCProvider
    seen=[]
    def handler(request):
        seen.append((request.url.path,request.headers.get('authorization'),json.loads(request.content)))
        return httpx.Response(200,content='\n'.join([event('response.output_text.delta',delta='ok'),event('response.completed')]),headers={'content-type':'text/event-stream'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async def token(): return 'fake-test-token'
            provider=SIWCProvider('test-model',token,client=client,origin='desktop-local',user_initiated=True)
            result=await provider.complete('system',[{'role':'user','content':'hi'}],[])
            assert result.text=='ok'
    from unittest.mock import patch
    from mcptoai_agent import siwc_gate
    with patch.object(siwc_gate, 'local_permission', return_value=True), patch('mcptoai_agent.siwc_auth.assert_owner', return_value='auth0|owner'):
        asyncio.run(run())
    assert seen[0][0]=='/v1/responses'
    assert seen[0][1]=='Bearer fake-test-token'
    assert seen[0][2]['store'] is False
