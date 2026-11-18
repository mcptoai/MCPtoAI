'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('fs');
const os=require('os');
const path=require('path');
const {repairLegacyPlist,launchctlGone}=require('./agent-install');

function scenario({bootstrapFailures=0,printDelay=0,permanent=false,initiallyRegistered=true}={}){
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'mcptoai-plist-'));
  const plist=path.join(dir,'agent.plist');
  fs.writeFileSync(plist,JSON.stringify({Label:'com.bkty.mcptoai.device-agent',ProgramArguments:['/test/agent','connect']}));
  const calls=[];let registered=initiallyRegistered,waiting=0,attempts=0;
  const run=(cmd,args)=>{
    calls.push([cmd,...args]);
    if(cmd==='/usr/bin/plutil'&&args.includes('json'))return JSON.stringify(JSON.parse(fs.readFileSync(plist,'utf8')));
    if(cmd==='/usr/bin/plutil'&&args.includes('xml1'))return '';
    if(cmd==='/bin/launchctl'){
      if(args.includes('bootout')){waiting=printDelay;return ''}
      if(args.includes('print')){if(waiting>0){waiting--;return ''}if(!registered)throw new Error('service not found');return ''}
      if(args.includes('bootstrap')){attempts++;if(permanent||attempts<=bootstrapFailures)throw Error('Bootstrap failed: 5: Input/output error');registered=true;return ''}
    }
    return '';
  };
  return {plist,calls,run,close:()=>fs.rmSync(dir,{recursive:true,force:true}),get attempts(){return attempts},
    waitForGone:({run,service})=>{registered=false;return launchctlGone({run,service,timeoutMs:500,pollMs:1,wait:()=>{}})}};
}

test('plist updated once, bootout settles before bootstrap, unchanged starts never reload',()=>{
  const f=scenario({printDelay:3});
  try{
    assert.deepEqual(repairLegacyPlist({...f,wait:()=>{}}),{ok:true,changed:true,reloaded:true,started:true,attempts:1});
    const ops=f.calls.map(c=>c[1]);
    assert(ops.indexOf('bootout')>=0&&ops.indexOf('bootstrap')>ops.indexOf('bootout'));
    const before=f.calls.length;
    assert.deepEqual(repairLegacyPlist({...f,wait:()=>{}}),{ok:true,changed:false});
    assert.equal(f.calls.length,before+2);
    assert.equal(f.attempts,1);
  }finally{f.close()}
});
test('transient bootstrap failure retries only once',()=>{
  const f=scenario({bootstrapFailures:1});
  try{const result=repairLegacyPlist({...f,wait:()=>{}});assert.equal(result.ok,true);assert.equal(result.attempts,2);assert.equal(f.attempts,2)}finally{f.close()}
});
test('second bootstrap failure reports explicit error, never silently successful',()=>{
  const f=scenario({permanent:true});
  try{const result=repairLegacyPlist({...f,wait:()=>{}});assert.equal(result.ok,false);assert.match(result.error,/after two attempts/);assert.equal(f.attempts,2)}finally{f.close()}
});
test('bootout timeout stops before any bootstrap',()=>{
  const f=scenario();
  try{const result=repairLegacyPlist({...f,waitForGone:()=>false});assert.equal(result.ok,false);assert.match(result.error,/bootout timeout/);assert.equal(f.attempts,0)}finally{f.close()}
});
test('correct plist with missing service bootstraps without restarting an existing agent',()=>{
  const f=scenario({initiallyRegistered:false});
  try {
    fs.writeFileSync(f.plist,JSON.stringify({Label:'com.bkty.mcptoai.device-agent',AssociatedBundleIdentifiers:['com.bkty.mcptoai.desktop']}));
    const result=repairLegacyPlist({...f,wait:()=>{}});
    assert.equal(result.ok,true);assert.equal(result.changed,false);assert.equal(f.attempts,1);
    assert.equal(f.calls.filter(c=>c.includes('bootout')).length,0);
  }finally{f.close()}
});
test('startup shows explicit user-facing error if registration fails',()=>{
  const source=fs.readFileSync(path.join(__dirname,'main.js'),'utf8');
  assert.match(source,/Legacy LaunchAgent repair failed/);
  assert.match(source,/await dialog\.showMessageBox\(\{type:'error',title:'MCPtoAI — Device Agent could not start'/);
});
