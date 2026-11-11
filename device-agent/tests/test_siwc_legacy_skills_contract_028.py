"""Preserve the working 0.2.6 SIWC + skills/tool-call contract.

Uses synthetic token and mocked HTTP. Does not enable web SIWC.
"""
import asyncio
import json
from unittest.mock import patch
import httpx
from mcptoai_agent.providers.siwc_provider import SIWCProvider
from mcptoai_agent.providers.base import ToolSpec, ToolCall
from mcptoai_agent import siwc_gate


def test_siwc_skill_tool_call_and_result_roundtrip():
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            events = [
                {'type':'response.output_item.done','item':{'type':'function_call','call_id':'skill-call-1','name':'load_skill','arguments':'{"name":"example"}'}},
                {'type':'response.completed'},
            ]
        else:
            events = [{'type':'response.output_text.delta','delta':'Skill loaded'}, {'type':'response.completed'}]
        return httpx.Response(200, content='\n'.join('data: '+json.dumps(x) for x in events), headers={'content-type':'text/event-stream'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async def token(): return 'synthetic-token'
            provider = SIWCProvider('test-model', token, client=client, origin='desktop-local', user_initiated=True)
            tools = [ToolSpec('load_skill', 'Load a skill', {'type':'object','properties':{'name':{'type':'string'}}})]
            first = await provider.complete('system', [{'role':'user','content':'Load the skill'}], tools)
            assert first.tool_calls[0].name == 'load_skill'
            assert first.tool_calls[0].arguments == {'name':'example'}
            history = [
                {'role':'user','content':'Load the skill'},
                {'role':'assistant','content':'','tool_calls':[ToolCall('skill-call-1','load_skill',{'name':'example'})]},
                {'role':'tool','tool_call_id':'skill-call-1','content':'Skill content'},
            ]
            second = await provider.complete('system', history, tools)
            assert second.text == 'Skill loaded'
    with patch.object(siwc_gate,'local_permission',return_value=True), patch('mcptoai_agent.siwc_auth.assert_owner',return_value='auth0|owner'):
        asyncio.run(run())
    assert len(requests) == 2
    assert requests[0]['tools'][0]['name'] == 'load_skill'
    assert requests[1]['input'][1]['call_id'] == requests[1]['input'][2]['call_id'] == 'skill-call-1'
    assert all(req['store'] is False for req in requests)
