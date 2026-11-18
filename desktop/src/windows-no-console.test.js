'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const load=name=>fs.readFileSync(path.join(__dirname,name),'utf8');
test('Windows agent lifecycle never creates visible child consoles',()=>{
  const install=load('agent-install-windows.js');
  for(const line of install.split(/\r?\n/).filter(line=>line.includes('execFileSync(')&&!line.includes('require('))) {
    assert.match(line,/windowsHide:true/,`visible Windows child process: ${line}`);
  }
  assert.match(load('platform.js'),/execFile\(cmd,args,\{[^}]*windowsHide:true/);
  const handover=load('agent-handover.js');
  assert.match(handover,/execFileSync\('powershell\.exe'[^\n]*windowsHide:true/);
  assert.match(handover,/execFileSync\(current,\['--version'\][^\n]*windowsHide:true/);
});
