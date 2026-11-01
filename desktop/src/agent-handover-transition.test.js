'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {handoverOnStartup}=require('./agent-handover');
const mac='/Applications/MCPtoAI.app/Contents/Library/LoginItems/MCPtoAI Device Agent.app/Contents/Resources/agent/mcptoai-agent';
const win='C:\\Users\\test\\AppData\\Local\\MCPtoAI\\Agent\\mcptoai-agent.exe';
function fixture({platform='darwin',current=mac,previous='0.2.5',entries=[]}={}){
  const state={entries:entries.map(e=>({...e,commandLine:e.commandLine||e.exe+' connect'})),stops:0,starts:0,restarts:0,killed:[],written:null};
  const ops={current,platform,version:'0.2.7',configRoot:'/config',
    readFile:()=>{if(previous===null){const e=new Error('missing');e.code='ENOENT';throw e}return JSON.stringify({version:previous})},
    writeFile:(_p,data)=>{state.written=JSON.parse(data).version},
    mkdir:()=>{},rename:()=>{},unlink:()=>{},
    enumerate:()=>state.entries,
    terminate:async e=>{state.killed.push(e.pid);state.entries=state.entries.filter(x=>x.pid!==e.pid);return true},
    serviceRestart:async()=>{state.restarts++;state.entries=state.entries.filter(e=>e.pid!==101);state.entries.push({pid:501,exe:current,commandLine:current+' connect'});return {ok:true}},
    servicePid:async()=>501,
    serviceStop:async()=>{state.stops++;return {ok:true}},
    serviceStart:async()=>{state.starts++;return {ok:true}}};
  return {state,ops};
}
test('0.2.5 to 0.2.7 closes all managed agents and starts once',async()=>{
  const f=fixture({entries:[{pid:101,exe:mac},{pid:102,exe:mac}]});
  const r=await handoverOnStartup(f.ops);
  assert.equal(r.ok,true);assert.deepEqual(f.state.killed,[102]);assert.equal(f.state.restarts,1);assert.equal(f.state.starts,0);assert.equal(f.state.written,'0.2.7');
});
test('same Desktop version leaves agent untouched',async()=>{
  const f=fixture({previous:'0.2.7',entries:[{pid:101,exe:mac}]});
  const r=await handoverOnStartup(f.ops);
  assert.equal(r.changed,false);assert.equal(f.state.stops,0);assert.equal(f.state.starts,0);assert.deepEqual(f.state.killed,[]);
});
test('Windows legacy agent without --version is stopped without probing binary',async()=>{
  const f=fixture({platform:'win32',current:win,previous:null,entries:[{pid:201,exe:win}]});
  const r=await handoverOnStartup(f.ops);
  assert.equal(r.ok,true);assert.deepEqual(f.state.killed,[201]);assert.equal(f.state.starts,1);
});
test('unrelated process is preserved',async()=>{
  const f=fixture({entries:[{pid:301,exe:'/usr/local/bin/mcptoai-agent'},{pid:302,exe:mac}]});
  await handoverOnStartup(f.ops);
  assert.deepEqual(f.state.killed,[302]);assert.deepEqual(f.state.entries.map(e=>e.pid),[301,501]);
});

test('launchd restart keeps supervised PID and closes manually started legacy agent',async()=>{
 const f=fixture({entries:[{pid:101,exe:mac},{pid:777,exe:mac}]});
 const r=await handoverOnStartup(f.ops);
 assert.equal(r.ok,true);assert.equal(r.keeper,501);assert.deepEqual(f.state.killed,[777]);assert.deepEqual(f.state.entries.map(e=>e.pid),[501]);
});
test('launchd PID lookup failure does not kill arbitrary managed processes or mark success',async()=>{
 const f=fixture({entries:[{pid:101,exe:mac}]});f.ops.servicePid=async()=>null;
 const r=await handoverOnStartup(f.ops);
 assert.equal(r.ok,false);assert.deepEqual(f.state.killed,[]);assert.equal(f.state.written,null);
});

test('missing marker forces one-time handover even when disk binary is current',async()=>{
 const f=fixture({previous:null,entries:[{pid:101,exe:mac}]});f.ops.probeVersion=async()=> '0.2.7';
 const first=await handoverOnStartup(f.ops);assert.equal(first.ok,true);assert.equal(f.state.restarts,1);assert.equal(f.state.written,'0.2.7');
 const second=await handoverOnStartup({...f.ops,readFile:()=>JSON.stringify({version:'0.2.7'})});assert.equal(second.changed,false);assert.equal(f.state.restarts,1);
});
test('same marker cleans duplicate connect but preserves Drive subprocess',async()=>{
 const f=fixture({previous:'0.2.7',entries:[{pid:501,exe:mac},{pid:777,exe:mac},{pid:888,exe:mac,commandLine:mac+' google-drive-mcp'}]});
 const r=await handoverOnStartup(f.ops);assert.equal(r.ok,true);assert.equal(f.state.restarts,0);assert.deepEqual(f.state.killed,[777]);assert.deepEqual(f.state.entries.map(e=>e.pid),[501,888]);
});


test('delayed launchd PID after kickstart writes marker and preserves new connect',async()=>{
 const f=fixture({previous:null,entries:[{pid:101,exe:mac}]});
 f.ops.probeVersion=async()=> '0.2.7';let polls=0;
 f.ops.servicePid=async()=> ++polls<=3?null:501;
 const result=await handoverOnStartup(f.ops);
 assert.equal(result.ok,true);assert.equal(result.keeper,501);
 assert.equal(f.state.restarts,1);assert.equal(f.state.written,'0.2.7');assert.ok(polls>=4);
});
test('launchd PID unavailable but newly started sole connect allows marker persistence',async()=>{
 const f=fixture({previous:null,entries:[{pid:101,exe:mac}]});
 f.ops.probeVersion=async()=> '0.2.7';f.ops.servicePid=async()=>null;
 const result=await handoverOnStartup(f.ops);
 assert.equal(result.ok,true);assert.equal(result.fallback,true);assert.equal(f.state.written,'0.2.7');
});

test('real macOS ps output: spaced bundle path, connect only, Drive excluded',()=>{
 const {parseMacPs}=require('./agent-handover');
 const sample=[
 '19269 /Applications/MCPtoAI.app/Contents/Library/LoginItems/MCPtoAI Device Agent.app/Contents/Resources/agent/mcptoai-agent connect',
 '19504 /Applications/MCPtoAI.app/Contents/Library/LoginItems/MCPtoAI Device Agent.app/Contents/Resources/agent/mcptoai-agent google-drive-mcp'
 ].join('\n');
 const entries=parseMacPs(sample);
 assert.equal(entries.length,2);
 assert.equal(entries[0].exe,mac);
 assert.equal(entries[0].commandLine,mac+' connect');
 assert.equal(entries[1].commandLine,mac+' google-drive-mcp');
});
test('real launchctl print output parses service PID rather than app PID',()=>{
 const {parseLaunchdPid}=require('./platform');
 const sample='gui/501/com.bkty.mcptoai.device-agent = {\n\tstate = running\n\tpid = 19269\n\tforks = 2\n}';
 assert.equal(parseLaunchdPid(sample),19269);
 assert.equal(parseLaunchdPid('state = waiting\n'),null);
});
