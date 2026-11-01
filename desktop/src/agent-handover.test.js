const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const {managed,reconcile,stopForInstall} = require('./agent-handover');

const current = '/Applications/MCPtoAI.app/Contents/Library/LoginItems/MCPtoAI Device Agent.app/Contents/Resources/agent/mcptoai-agent';

test('old agent started before installation is terminated; new agent remains',async()=>{
  const killed=[];
  const result=await reconcile({current,platform:'darwin',installedAt:200000,entries:[{pid:111,exe:current},{pid:222,exe:current}],inspect:async entry=>({startedAt:entry.pid===111?100000:300000}),terminate:async entry=>{killed.push(entry.pid);return true}});
  assert.deepEqual(killed,[111]);
  assert.equal(result.ok,true);
});

test('unrelated processes cannot be terminated',async()=>{
  const killed=[];
  await reconcile({current,platform:'darwin',installedAt:200000,entries:[{pid:10,exe:'/usr/local/bin/mcptoai-agent'},{pid:11,exe:'/usr/bin/python3'}],inspect:async()=>({startedAt:0}),terminate:async entry=>{killed.push(entry.pid);return true}});
  assert.deepEqual(killed,[]);
});

test('Windows agent path validation',()=>{
  const win='C:\\Users\\Test\\AppData\\Local\\MCPtoAI\\Agent\\mcptoai-agent.exe';
  assert.equal(managed(win,win,'win32'),true);
  assert.equal(managed('C:\\Other\\mcptoai-agent.exe',win,'win32'),false);
});

test('OTA install is blocked when an agent will not exit',async()=>{
  const result=await stopForInstall({current,platform:'darwin',serviceStop:async()=>({ok:true}),enumerate:()=>[{pid:1,exe:current}],terminate:async()=>false});
  assert.equal(result.ok,false);
});

test('OTA install proceeds only after all agent processes exit',async()=>{
  let count=0;
  const result=await stopForInstall({current,platform:'darwin',serviceStop:async()=>({ok:true}),enumerate:()=>++count===1?[{pid:1,exe:current}]:[],terminate:async()=>true});
  assert.equal(result.ok,true);
});
