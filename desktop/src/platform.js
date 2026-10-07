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
const psq=v=>`'${String(v).replace(/'/g,"''")}'`;
const winPs=script=>run('powershell.exe',['-NoProfile','-NonInteractive','-Command',script]);
async function winStatus(){const exe=WIN_EXE();if(!fs.existsSync(exe))return {running:false,installed:false,detail:'Device Agent is not installed'};const r=await winPs(`$exe=${psq(exe)};$p=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $exe -and $_.CommandLine -match '(?i)(^|\\s)connect(\\s|$)' };if($p){'RUNNING'}else{'STOPPED'}`);const running=r.ok&&r.stdout.trim()==='RUNNING';return {running,installed:true,detail:running?'Agent is running':'Agent is installed but stopped'}}
async function winStart(){const exe=WIN_EXE();if(!fs.existsSync(exe))return {ok:false,stderr:'Device Agent is not installed. Use Install / Repair first.'};const s=await winStatus();if(s.running)return {ok:true,stdout:'Agent is already running',stderr:''};return winPs(`Start-Process -FilePath ${psq(exe)} -ArgumentList 'connect' -WindowStyle Hidden`)}
async function winStop(){const exe=WIN_EXE();if(!fs.existsSync(exe))return {ok:true,stdout:'Agent is not installed',stderr:''};return winPs(`$exe=${psq(exe)};$p=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $exe -and $_.CommandLine -match '(?i)(^|\\s)connect(\\s|$)' };foreach($x in $p){Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue};'Agent stopped'`)}
function adapter(){
 if(process.platform==='darwin') return {
  platform:'macOS',
  async status(){const r=await run('launchctl',['print',MAC_SERVICE()]);return {running:r.ok,detail:r.ok?'Agent is running':'Agent is stopped'}},
  async start(){const plist=MAC_PLIST();if(!fs.existsSync(plist))return {ok:false,stderr:'Device Agent LaunchAgent is not installed. Use Install / Repair first.'};let r=await run('launchctl',['print',MAC_SERVICE()]);if(!r.ok){r=await run('launchctl',['bootstrap',MAC_DOMAIN(),plist]);if(!r.ok&&!(r.stderr||'').includes('service already loaded'))return r}return run('launchctl',['kickstart',MAC_SERVICE()])},
  async restart(){const plist=MAC_PLIST();if(!fs.existsSync(plist))return {ok:false,stderr:'Device Agent LaunchAgent is not installed. Use Install / Repair first.'};let r=await run('launchctl',['print',MAC_SERVICE()]);if(!r.ok){r=await run('launchctl',['bootstrap',MAC_DOMAIN(),plist]);if(!r.ok)return r;return run('launchctl',['kickstart',MAC_SERVICE()])}return run('launchctl',['kickstart','-k',MAC_SERVICE()])},
  async stop(){const first=await run('launchctl',['bootout',MAC_SERVICE()]);await new Promise(r=>setTimeout(r,350));const check=await run('launchctl',['print',MAC_SERVICE()]);if(check.ok)return {ok:false,stderr:'Device Agent service is still loaded after Stop.'};const exe=path.join(os.homedir(),'Applications','MCPtoAI Device Agent.app','Contents','Resources','agent','mcptoai-agent');const pids=await run('/usr/bin/pgrep',['-f',exe+' connect']);if(pids.ok&&pids.stdout){for(const pid of pids.stdout.split(/\s+/).filter(Boolean))await run('/bin/kill',['-TERM',pid]);await new Promise(r=>setTimeout(r,300));const left=await run('/usr/bin/pgrep',['-f',exe+' connect']);if(left.ok&&left.stdout)return {ok:false,stderr:'Device Agent process is still running after Stop.'}}return {ok:true,stdout:first.ok?'Agent stopped':'Agent was already stopped',stderr:''}},
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
