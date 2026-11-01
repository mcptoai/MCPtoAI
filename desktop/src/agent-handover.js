'use strict';
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const canonical = p => {try {return fs.realpathSync(p)} catch {return path.resolve(p)}};
const managed = (candidate, current, platform) => {
  const p = platform === 'win32' ? path.win32 : path;
  const actual = platform === 'win32' ? p.normalize(candidate).toLowerCase() : canonical(candidate), expected = platform === 'win32' ? p.normalize(current).toLowerCase() : canonical(current);
  if (p.basename(actual).toLowerCase() !== (platform === 'win32' ? 'mcptoai-agent.exe' : 'mcptoai-agent')) return false;
  if (actual === expected) return true;
  if (platform === 'darwin' && actual === canonical(path.join(require('os').homedir(),'Applications','MCPtoAI Device Agent.app','Contents','Resources','agent','mcptoai-agent'))) return true;
  const root = platform === 'win32' ? p.dirname(p.dirname(expected)) : path.dirname(path.dirname(path.dirname(path.dirname(path.dirname(expected)))));
  return actual.startsWith(root + p.sep) && actual.includes('MCPtoAI');
};
const parseMacPs = out => out.split('\n').map(line => {
  const m=line.trim().match(/^(\d+)\s+(\/.*?mcptoai-agent)(?=\s|$)(.*)$/);
  return m?{pid:Number(m[1]),exe:m[2],commandLine:m[2]+m[3]}:null;
}).filter(Boolean);
const list = platform => {
  if (platform === 'darwin') {
    return parseMacPs(execFileSync('ps',['-ww','-axo','pid=,command='],{encoding:'utf8',timeout:8000}));
  }
  if (platform === 'win32') {
    const script = 'Get-CimInstance Win32_Process -Filter "Name = \'mcptoai-agent.exe\'" | Select-Object ProcessId,ExecutablePath,CommandLine,CreationDate | ConvertTo-Json -Compress';
    const out = execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{encoding:'utf8',timeout:10000}).trim();
    return (out ? [JSON.parse(out)].flat() : []).map(x => ({pid:x.ProcessId,exe:x.ExecutablePath,commandLine:x.CommandLine,startedAt:Date.parse(x.CreationDate)})).filter(x => x.exe);
  }
  return [];
};
const isConnect = entry => /(?:^|[\s"'])connect(?:[\s"']|$)/.test(String(entry.commandLine||''));
const running = pid => {try {process.kill(pid,0);return true} catch(e) {return e.code === 'EPERM'}};
const stop = async (entry, ops = {}) => {
  const signal = ops.signal || ((pid, sig) => process.kill(pid,sig));
  const alive = ops.alive || running;
  signal(entry.pid,'SIGTERM');
  for(let i=0;i<20;i++) {if(!alive(entry.pid))return true;await sleep(100)}
  return !alive(entry.pid);
};
const reconcile = async ({current,platform=process.platform,entries=list(platform),installedAt=fs.statSync(current).mtimeMs,version,inspect,terminate=stop}) => {
  const installedVersion = version && !inspect ? execFileSync(current,['--version'],{encoding:'utf8',timeout:5000}).match(/mcptoai-agent\s+(\d+\.\d+\.\d+)/)?.[1] : null;
  if(version && !inspect && !installedVersion)return {ok:false,error:'Cannot verify managed agent version'};
  const results=[];
  for(const entry of entries) {
    if(!managed(entry.exe,current,platform) || entry.pid === process.pid)continue;
    const info=inspect ? await inspect(entry) : {startedAt: platform==='darwin' ? Date.parse(execFileSync('ps',['-p',String(entry.pid),'-o','lstart='],{encoding:'utf8'}).trim()) : entry.startedAt};
    // A replaced binary retains the same pathname: start-before-install proves staleness.
    const stale=(version && installedVersion && installedVersion!==version) || entry.exe!==current || (Number.isFinite(info.startedAt) && info.startedAt < installedAt - 1000);
    if(!stale)continue;
    const ok=await terminate(entry);
    results.push({pid:entry.pid,ok});
  }
  return {ok:results.every(x=>x.ok),results,version};
};
// Persist the last successfully reconciled Desktop version, not the on-disk agent version.
// A missing marker is a legacy installation (0.2.5 did not write this marker).
const handoverOnStartup = async ({current,version,configRoot,platform=process.platform,enumerate=list,terminate=stop,serviceStop,serviceStart,serviceRestart,servicePid,readFile=fs.readFileSync,writeFile=fs.writeFileSync,mkdir=fs.mkdirSync,rename=fs.renameSync,unlink=fs.unlinkSync,probeVersion,log=()=>{}}) => {
  const marker=path.join(configRoot,'desktop-agent-handover.json');
  const persist=()=>{log('handover marker write attempt '+marker+' version='+version);mkdir(configRoot,{recursive:true});const tmp=marker+'.'+process.pid+'.tmp';try{writeFile(tmp,JSON.stringify({version},null,2)+'\n',{mode:0o600});rename(tmp,marker);log('handover marker write success '+marker)}catch(e){try{unlink(tmp)}catch{};log('handover marker write FAILED '+marker+' '+e.message);console.error('Agent handover marker write failed',marker,e);throw e}};
  let previous=null;
  try {previous=JSON.parse(readFile(marker,'utf8')).version;log('handover marker read '+marker+' version='+previous)} catch(e) {log('handover marker read failed '+marker+' '+e.message);if(e.code!=='ENOENT')log('handover marker unreadable, probing running agent before any restart')}
  const targets=()=>enumerate(platform).filter(e=>e.pid!==process.pid && managed(e.exe,current,platform) && isConnect(e));
  const cleanup=async()=>{
    const entries=targets();if(entries.length<=1)return {ok:true,removed:[]};
    const keeper=platform==='darwin'?await servicePid():null;
    if(platform==='darwin'&&(!Number.isSafeInteger(keeper)||!entries.some(e=>e.pid===keeper)))return {ok:false,error:'Cannot identify launchd connect PID'};
    // Windows has no launchd: retain one known connect process, never terminate children.
    const keep=platform==='darwin'?keeper:entries[0].pid;
    const removed=[];for(const e of entries.filter(e=>e.pid!==keep)){
      log('duplicate connect cleanup pid='+e.pid+' keeper='+keep);
      const ok=await terminate(e);removed.push({pid:e.pid,ok});if(!ok)return {ok:false,error:'Could not stop duplicate connect',removed};
    }return {ok:true,removed};
  };
  if(previous===version){const c=await cleanup();if(!c.ok)return c;log('same version, untouched (marker)');return {ok:true,changed:false,cleanup:c.removed}};
  if(previous===null)log('no marker → one-time handover');
  else log('marker mismatch or unreadable → version handover');
  // The binary on disk may already be upgraded while an older connect process lives.
  // A missing marker MUST trigger one handover, regardless of disk --version.
  if(probeVersion){try{const actual=await probeVersion();if(!actual){log('version probe unavailable, no restart');return {ok:false,error:'Agent version could not be verified safely'}}log('disk agent version='+actual)}catch(e){log('version probe exception, no restart '+e.message);return {ok:false,error:'Agent version probe failed'}}}
  const stopped=[];
  if(platform==='darwin'){
    const reason=previous===null?'no marker → one-time handover':'marker mismatch → version handover';
    log('handover: '+reason+'; launchctl kickstart -k requested');
    const before=targets().map(e=>e.pid);
    const restarted=await serviceRestart();
    if(!restarted?.ok)return {ok:false,error:'Could not restart launchd agent'};
    const restartedAt=Date.now();
    // launchd can report no PID for several seconds after a successful kickstart.
    const deadline=Date.now()+15000;
    let keeper=null,observed=[];
    while(Date.now()<deadline){
      keeper=await servicePid();observed=targets();
      log('handover: launchd PID poll pid='+keeper+' connect='+observed.map(e=>e.pid).join(','));
      if(Number.isSafeInteger(keeper)&&keeper>0&&observed.some(e=>e.pid===keeper))break;
      keeper=null;await sleep(250);
    }
    if(!keeper){
      // Fallback must establish a new process, not simply trust the old binary path.
      const only=observed.length===1?observed[0]:null;
      if(only&&!before.includes(only.pid)){
        log('handover: launchd PID unavailable, verifying post-kickstart sole connect pid='+only.pid);
        if(probeVersion&&await probeVersion()===version){persist();return {ok:true,changed:true,fallback:true,keeper:only.pid,stopped}};
      }
      return {ok:false,error:'Cannot identify launchd agent PID after 15s',stopped};
    }
    for(const entry of targets().filter(e=>e.pid!==keeper)){
      log('handover: terminating duplicate connect pid='+entry.pid+' keeper='+keeper);
      const ok=await terminate(entry);stopped.push({pid:entry.pid,ok});
      if(!ok)return {ok:false,error:'Managed agent did not exit',stopped};
    }
    const remaining=targets();
    if(remaining.length===1&&remaining[0].pid===keeper){persist();return {ok:true,changed:true,stopped,keeper}};
    return {ok:false,error:'Managed launchd agent did not settle to one process',stopped};
  }
  const service=await serviceStop();
  if(!service?.ok)return {ok:false,error:'Could not stop managed agent service'};
  for(let pass=0;pass<4;pass++){
    const entries=targets();
    if(!entries.length)break;
    for(const entry of entries){
      const ok=await terminate(entry);stopped.push({pid:entry.pid,ok});
      if(!ok)return {ok:false,error:'Managed agent did not exit',stopped};
    }
    await sleep(250);
  }
  if(targets().length)return {ok:false,error:'Managed agent remains running',stopped};
  const started=await serviceStart();
  if(!started?.ok)return {ok:false,error:'Could not start managed agent service',stopped};
  persist();
  return {ok:true,changed:true,stopped};
};
module.exports={managed,list,parseMacPs,stop,reconcile,handoverOnStartup};

const stopForInstall = async ({current,platform=process.platform,serviceStop,enumerate=list,terminate=stop}) => {
  const service = await serviceStop();
  if (!service?.ok) return {ok:false,error:'Could not stop agent service'};
  for (const entry of enumerate(platform)) {
    if (!managed(entry.exe,current,platform)) continue;
    if (!await terminate(entry)) return {ok:false,error:`Agent PID ${entry.pid} did not exit`};
  }
  await sleep(250);
  if (enumerate(platform).some(entry => managed(entry.exe,current,platform)))
    return {ok:false,error:'Agent still running; update installation cancelled'};
  return {ok:true};
};
module.exports.stopForInstall=stopForInstall;
