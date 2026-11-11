'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=__dirname;
test('Windows installed autostart uses supervisor, not bare connect',()=>{
 const source=fs.readFileSync(path.join(root,'agent-install-windows.js'),'utf8');
 assert.match(source,/const cmd=`"\$\{exe\}" supervise`/);
 assert.match(source,/spawn\(exe,\['supervise'\]/);
});
test('Windows Stop terminates supervisor process tree',()=>{
 const source=fs.readFileSync(path.join(root,'platform.js'),'utf8');
 assert.match(source,/taskkill\.exe \/PID \$x\.ProcessId \/T \/F/);
 assert.match(source,/\$supervisors/);
});
test('Desktop Quit does not call platform.stop',()=>{
 const source=fs.readFileSync(path.join(root,'main.js'),'utf8');
 assert.match(source,/before-quit',\(\)=>handoverLog\('Desktop Quit: no agent action'\)/);
});
