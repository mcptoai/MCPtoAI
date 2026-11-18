'use strict';
// All Desktop-owned Windows CLI subprocesses must be launched without a visible
// console window, including the long-lived cloud-ipc-jsonl/desktop-chat-jsonl
// streams. Unlike hiding the Electron window this controls the CHILD console.
const childProcess=require('node:child_process');

function hideOptions(args, platform=process.platform){
  if(platform!=='win32')return args;
  const copy=[...args];
  let callback;
  if(typeof copy[copy.length-1]==='function')callback=copy.pop();
  const last=copy[copy.length-1];
  if(last&&typeof last==='object'&&!Array.isArray(last)&&!Buffer.isBuffer(last)){
    copy[copy.length-1]={...last,windowsHide:true};
  }else{
    copy.push({windowsHide:true});
  }
  if(callback)copy.push(callback);
  return copy;
}
const wrap=name=>(...args)=>childProcess[name](...hideOptions(args));
module.exports={
  spawn:wrap('spawn'),spawnSync:wrap('spawnSync'),
  execFile:wrap('execFile'),execFileSync:wrap('execFileSync'),
  exec:wrap('exec'),execSync:wrap('execSync'),hideOptions,
};
