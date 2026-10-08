const {execFile}=require('child_process');
const os=require('os');
const path=require('path');
const fs=require('fs');
const run=(cmd,args=[])=>new Promise(resolve=>execFile(cmd,args,{timeout:10000},(error,stdout,stderr)=>resolve({ok:!error,stdout:String(stdout||'').trim(),stderr:String(stderr||'').trim()})));
const LABEL='com.bkty.mcptoai.device-agent';
const MAC_DOMAIN=()=>`gui/${process.getuid()}`;
const MAC_SERVICE=()=>`${MAC_DOMAIN()}/${LABEL}`;
const MAC_PLIST=()=>path.join(os.homedir(),'Library','LaunchAgents',`${LABEL}.plist`);
const WIN_EXE=()=>path.join(process.env.LOCALAPPDATA||path.join(os.homedir(),'AppData','Local'),'MCPtoAI','Agent','mcptoai-agent.exe');
const REMOVED_MARKER=()=>process.platform==='win32'?path.join(process.env.APPDATA||path.join(os.homedir(),'AppData','Roaming'),'MCPtoAI','device-removed.json'):path.join(os.homedir(),'.config','mcptoai','device-removed.json');
const removedStatus=()=>fs.existsSync(REMOVED_MARKER())?{running:false,installed:true,removed:true,detail:'This device was removed. Sign in again to pair it.'}:null;
const psq=v=>`'${String(v).replace(/'/g,"''")}'`;
const winPs=script=>run('powershell.exe',['-NoProfile','-NonInteractive','-Command',script]);
async function winStatus(){const removed=removedStatus();if(removed)return removed;const exe=WIN_EXE();if(!fs.existsSync(exe))return {running:false,installed:false,detail:'Device Agent is not installed'};const r=await winPs(`$exe=${psq(exe)};$p=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $exe -and $_.CommandLine -match '(?i)(^|\\s)connect(\\s|$)' };if($p){'RUNNING'}else{'STOPPED'}`);const running=r.ok&&r.stdout.trim()==='RUNNING';return {running,installed:true,detail:running?'Agent is running':'Agent is installed but stopped'}}
async function winStart(){const exe=WIN_EXE();if(!fs.existsSync(exe))return {ok:false,stderr:'Device Agent is not installed. Use Install / Repair first.'};const s=await winStatus();if(s.running)return {ok:true,stdout:'Agent is already running',stderr:''};return winPs(`Start-Process -FilePath ${psq(exe)} -ArgumentList 'connect' -WindowStyle Hidden`)}
async function winStop(){const exe=WIN_EXE();if(!fs.existsSync(exe))return {ok:true,stdout:'Agent is not installed',stderr:''};return winPs(`$exe=${psq(exe)};$p=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $exe -and $_.CommandLine -match '(?i)(^|\\s)connect(\\s|$)' };foreach($x in $p){Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue};'Agent stopped'`)}
function adapter(){
 if(process.platform==='darwin') return {
  platform:'macOS',
  async status(){const removed=removedStatus();if(removed)return removed;const r=await run('launchctl',['print',MAC_SERVICE()]);return {running:r.ok,installed:r.ok,detail:r.ok?'Agent is running':'Agent is stopped'}},
  async start(){const r=await run('launchctl',['print',MAC_SERVICE()]);if(!r.ok)return {ok:false,stderr:'Device Agent background service is not registered. Use Install / Repair first.'};return run('launchctl',['kickstart',MAC_SERVICE()])},
  async restart(){const r=await run('launchctl',['print',MAC_SERVICE()]);if(!r.ok)return {ok:false,stderr:'Device Agent background service is not registered. Use Install / Repair first.'};return run('launchctl',['kickstart','-k',MAC_SERVICE()])},
  async stop(){const before=await run('launchctl',['print',MAC_SERVICE()]);if(!before.ok)return {ok:true,stdout:'Agent is already stopped',stderr:''};const killed=await run('launchctl',['kill','SIGTERM',MAC_SERVICE()]);await new Promise(r=>setTimeout(r,500));return killed.ok?{ok:true,stdout:'Agent stopped',stderr:''}:killed},
  logPath:path.join(os.homedir(),'Library/Logs/MCPtoAI/agent.log')
 };
 if(process.platform==='win32') return {
  platform:'Windows',
  status:winStatus,
  start:winStart,
  async restart(){await winStop();return winStart()},
  stop:winStop,
  logPath:path.join(process.env.LOCALAPPDATA||path.join(os.homedir(),'AppData','Local'),'MCPtoAI','Logs','agent.log')
 };
 return {platform:'Linux',async status(){return {running:false,detail:'Linux service adapter pending'}},async start(){return {ok:false}},async restart(){return {ok:false}},async stop(){return {ok:false}},logPath:''};
}
module.exports={adapter};
