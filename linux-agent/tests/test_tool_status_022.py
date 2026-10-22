import asyncio
from dataclasses import replace
from fastmcp import FastMCP
from mcptoai_linux.agent import AgentSession
from mcptoai_linux.config import settings
from mcptoai_linux.providers.base import AssistantTurn,Provider,ToolCall

class OneCall(Provider):
 name='fake'
 def __init__(self,tool):super().__init__('none','fake');self.tool=tool;self.step=0
 async def complete(self,system,messages,tools):
  self.step+=1
  if self.step==1:return AssistantTurn(tool_calls=[ToolCall('call','broken_tool',{})])
  return AssistantTurn(text='Done')

def test_error_returned_as_text_must_be_failed(tmp_path):
 server=FastMCP('local')
 @server.tool
 def broken_tool()->str:return '[ERROR] simulated error'
 cfg=replace(settings,allowed_roots=[tmp_path]);session=AgentSession(cfg,OneCall('broken_tool'),server)
 events=[]
 async def emit(event):events.append(event)
 async def allow(*_):return True
 result=asyncio.run(session.run('Test failure',allow,emit))
 record=next(e for e in events if e['type']=='tool_result')
 assert record['status']=='failed' and record['is_error']
 assert session.history[-2]['is_error'] is True

def test_denied_approval_is_not_completed(tmp_path):
 server=FastMCP('local')
 @server.tool
 def broken_tool()->str:return 'should-not-run'
 cfg=replace(settings,allowed_roots=[tmp_path]);session=AgentSession(cfg,OneCall('broken_tool'),server)
 events=[]
 async def emit(event):events.append(event)
 async def deny(*_):return False
 asyncio.run(session.run('Test denial',deny,emit))
 record=next(e for e in events if e['type']=='tool_result')
 assert record['status']=='denied' and record['is_error']
