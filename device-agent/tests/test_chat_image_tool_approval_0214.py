"""Saved image path never inherits AUTO/session tool permissions."""
import asyncio
from dataclasses import replace
from io import BytesIO
from PIL import Image
import pytest
from mcptoai_agent.agent import AgentSession
from mcptoai_agent.config import settings
from mcptoai_agent.policy import Decision, ToolPolicy
from mcptoai_agent.providers.base import AssistantTurn, Provider, ToolCall
from mcptoai_agent.tools import build_server


class ToolUsingModel(Provider):
    name='chat-save-tool-test'
    def __init__(self, path):
        super().__init__('test','chat-save-tool-test')
        self.path=path;self.step=0;self.prompts=[]
    async def complete(self, system, messages, tools):
        self.prompts.append(system)
        self.step+=1
        if self.step == 1:
            return AssistantTurn(tool_calls=[ToolCall('image-tool-1','read_file',{'path':self.path})])
        return AssistantTurn(text='done')


@pytest.mark.parametrize('permission,approval,expected_calls',[
    (Decision.AUTO,False,1),
    (Decision.AUTO,True,1),
    (Decision.DENY,True,0),
])
def test_current_turn_image_forces_tool_confirmation(tmp_path,permission,approval,expected_calls):
    image=tmp_path/'saved.jpg'
    f=BytesIO();Image.new('RGB',(8,8),(20,30,40)).save(f,format='JPEG');image.write_bytes(f.getvalue())
    cfg=replace(settings,allowed_roots=[tmp_path.resolve()])
    model=ToolUsingModel(str(image))
    session=AgentSession(cfg,model,build_server(cfg),policy=ToolPolicy(rules={'read_file':permission}))
    calls=[];events=[]
    async def approver(name,args):
        calls.append((name,args));return approval
    async def emit(event):events.append(event)
    asyncio.run(session.run('Process saved image',approver,emit,saved_device_images=[str(image)]))
    assert len(calls)==expected_calls
    assert len(model.prompts)>=1 and str(image) in model.prompts[0]
    # Saved path is not independently added to persisted chat history content.
    assert all(str(image) not in str(item.get('content','')) for item in session.history if item.get('role')=='user')
    if not approval or permission is Decision.DENY:
        assert any(e.get('type')=='tool_result' and e.get('is_error') for e in events)


def test_regular_auto_read_does_not_prompt(tmp_path):
    path=tmp_path/'regular.txt';path.write_text('ordinary')
    cfg=replace(settings,allowed_roots=[tmp_path.resolve()])
    session=AgentSession(cfg,ToolUsingModel(str(path)),build_server(cfg),policy=ToolPolicy(rules={'read_file':Decision.AUTO}))
    async def no_approval(name,args):raise AssertionError('Ordinary AUTO read should not prompt')
    async def emit(event):pass
    asyncio.run(session.run('Read regular file',no_approval,emit))
