'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {hideOptions}=require('./hidden-child-process');

test('Windows child subprocess launch hides console without dropping options',()=>{
  const callback=()=>{};
  const a=hideOptions(['powershell.exe',['-Command','echo hi'],{stdio:'pipe',timeout:1000},callback],'win32');
  assert.deepEqual(a.slice(0,2),['powershell.exe',['-Command','echo hi']]);
  assert.deepEqual(a[2],{stdio:'pipe',timeout:1000,windowsHide:true});
  assert.strictEqual(a[3],callback);
  assert.deepEqual(hideOptions(['cmd.exe',['/c','echo hi']],'win32')[2],{windowsHide:true});
  assert.deepEqual(hideOptions(['cmd.exe',{windowsHide:false}],'win32')[1],{windowsHide:true});
  const original={stdio:'pipe'};
  hideOptions(['node',original],'win32');
  assert.deepEqual(original,{stdio:'pipe'});
});

test('non-Windows children retain original options',()=>{
  const values=['echo',['a'],{stdio:'pipe'}];
  assert.strictEqual(hideOptions(values,'darwin'),values);
});

test('Desktop launch modules use the central hidden child process wrapper',()=>{
  for(const name of ['main.js','platform.js','agent-handover.js','agent-install.js','agent-install-windows.js','github-mcp.js']){
    const source=fs.readFileSync(path.join(__dirname,name),'utf8');
    assert.match(source,/require\('\.\/hidden-child-process'\)/,name);
    assert.doesNotMatch(source,/require\(['"](?:node:)?child_process['"]\)/,name);
  }
});

test('packaged Windows cloud IPC prefers quiet agent while retaining pipe-based IPC',()=>{
  const vm=require('node:vm');
  const source=fs.readFileSync(path.join(__dirname,'main.js'),'utf8');
  const declaration=source.match(/^function cloudIpcAgentExecutable\(a\)\{[^\n]+\}$/m)?.[0];
  assert.ok(declaration,'Cloud IPC executable selection must be explicit');
  assert.match(source,/cloudIpcAgentExecutable\(agentExecutable\(\)\)/);
  assert.match(source,/child=spawn\(a\.cmd,\[\.\.\.a\.prefix,'cloud-ipc-jsonl'\],\{[^\n]*windowsHide:true/);
  function select(platform,available,prefix=[]){
    const ctx={process:{platform},path,fs:{existsSync:()=>available}};
    const fn=vm.runInNewContext('('+declaration+')',ctx);
    return fn({cmd:path.join('C:','Agent','mcptoai-agent.exe'),prefix,cwd:'C:Agent'});
  }
  assert.match(select('win32',true).cmd,/mcptoai-agent-background\.exe$/);
  assert.match(select('win32',false).cmd,/mcptoai-agent\.exe$/);
  assert.match(select('win32',true,['-m']).cmd,/mcptoai-agent\.exe$/);
  assert.match(select('darwin',true).cmd,/mcptoai-agent\.exe$/);
});
