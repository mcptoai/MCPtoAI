import asyncio
from dataclasses import replace
from pathlib import Path
from mcptoai_agent.agent import AgentSession
from mcptoai_agent.config import settings
from mcptoai_agent.preflight import validate
from mcptoai_agent.providers.base import AssistantTurn,Provider,ToolCall
from mcptoai_agent.tools import build_server

class ProviderFix(Provider):
 name='fake'
 def __init__(self,first,second):
  super().__init__('no-key','fake');self.first=str(first);self.second=str(second);self.step=0;self.observed=''
 async def complete(self,system,messages,tools):
  self.step+=1
  if self.step==1:return AssistantTurn(tool_calls=[ToolCall('a','write_file',{'path':self.first,'content':'a'})])
  if self.step==2:
   self.observed=messages[-1]['content']
   return AssistantTurn(tool_calls=[ToolCall('b','write_file',{'path':self.second,'content':'b'})])
  return AssistantTurn(text='done')

def test_blocked_then_model_corrects(tmp_path):
 bad=tmp_path/'.ssh'/'anything.txt';good=tmp_path/'okay.txt'
 cfg=replace(settings,allowed_roots=[tmp_path]);model=ProviderFix(bad,good)
 session=AgentSession(cfg,model,build_server(cfg));calls=[];events=[]
 async def approval(name,args):calls.append(args);return True
 async def emit(e):events.append(e)
 result=asyncio.run(session.run('save text',approval,emit,language='Turkish'))
 assert result=='done' and good.read_text()=='b'
 assert len(calls)==1 and calls[0]['_approval_meta']['file_action']=='new file'
 assert 'Protected location:' in model.observed
 assert any(e.get('type')=='text' and 'SSH keys' in e.get('text','') for e in events)
 assert not bad.exists()

def test_upload_preflight_size_and_extension(tmp_path):
 cfg=replace(settings,allowed_roots=[tmp_path]);good=tmp_path/'movie.mp4';good.write_bytes(b'12345')
 error,meta=validate('send_artifact',{'path':str(good)},cfg)
 assert error is None and meta['file_size_bytes']==5 and meta['file_type']=='.mp4'
 good.write_bytes(b'');assert 'size' in validate('send_artifact',{'path':str(good)},cfg)[0]
 other=tmp_path/'page.html';other.write_text('x');assert 'extension' in validate('send_artifact',{'path':str(other)},cfg)[0]

def test_no_approval_for_existing_write(tmp_path):
 cfg=replace(settings,allowed_roots=[tmp_path]);target=tmp_path/'file.txt';target.write_text('old')
 error,_=validate('write_file',{'path':str(target),'content':'new'},cfg);assert 'overwrite' in error
 error,meta=validate('write_file',{'path':str(target),'content':'new','overwrite':True},cfg)
 assert error is None and meta['file_action']=='overwrite'


class FindProvider(Provider):
 def __init__(self,root):super().__init__('no-key','fake');self.root=str(root);self.calls=0
 async def complete(self,system,messages,tools):
  self.calls+=1
  if self.calls==1:return AssistantTurn(tool_calls=[ToolCall('find','find_files',{'root':self.root,'pattern':'*.txt'})])
  return AssistantTurn(text='Finished')

def test_find_files_skips_protected_children(tmp_path):
 (tmp_path/'okay.txt').write_text('safe')
 blocked=tmp_path/'.ssh';blocked.mkdir();(blocked/'hidden.txt').write_text('example')
 cfg=replace(settings,allowed_roots=[tmp_path]);session=AgentSession(cfg,FindProvider(tmp_path),build_server(cfg));events=[]
 async def emit(e):events.append(e)
 async def approve(*_):return True
 asyncio.run(session.run('Search',approve,emit))
 outputs=[e for e in events if e.get('type')=='tool_result']
 assert outputs and outputs[0]['status']=='completed'
 assert 'okay.txt' in outputs[0]['preview']
 assert 'hidden.txt' not in outputs[0]['preview']
 assert '1 protected paths skipped' in outputs[0]['preview']

def test_sensitive_artifact_does_not_request_approval(tmp_path):
 secret=tmp_path/'.env';secret.write_text('not a credential')
 cfg=replace(settings,allowed_roots=[tmp_path])
 denial,meta=validate('send_artifact',{'path':str(secret)},cfg)
 assert denial=='Protected location: Environment secrets' and not meta
