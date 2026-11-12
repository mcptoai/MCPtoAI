const {execFile}=require('child_process');
const os=require('os');
const path=require('path');
const fs=require('fs');
// timedOut: komut zaman sınırını aştı (sonucu bilinmiyor; işlem arka planda tamamlanmış olabilir).
const run=(cmd,args=[],opts={})=>new Promise(resolve=>execFile(cmd,args,{timeout:opts.timeout||10000},(error,stdout,stderr)=>resolve({ok:!error,timedOut:Boolean(error&&error.killed),stdout:String(stdout||'').trim(),stderr:String(stderr||'').trim()})));
const LABEL='com.bkty.mcptoai.device-agent';
const MAC_DOMAIN=()=>`gui/${process.getuid()}`;
const MAC_SERVICE=()=>`${MAC_DOMAIN()}/${LABEL}`;
const MAC_PLIST=()=>path.join(os.homedir(),'Library','LaunchAgents',`${LABEL}.plist`);
const WIN_EXE=()=>path.join(process.env.LOCALAPPDATA||path.join(os.homedir(),'AppData','Local'),'MCPtoAI','Agent','mcptoai-agent.exe');
const parseLaunchdPid = output => {const m=String(output).match(/^\s*pid\s*=\s*(\d+)\s*$/m);return m?Number(m[1]):null};
const REMOVED_MARKER=()=>process.platform==='win32'?path.join(process.env.APPDATA||path.join(os.homedir(),'AppData','Roaming'),'MCPtoAI','device-removed.json'):path.join(os.homedir(),'.config','mcptoai','device-removed.json');
const removedStatus=()=>fs.existsSync(REMOVED_MARKER())?{running:false,installed:true,removed:true,detail:'This device was removed. Sign in again to pair it.'}:null;
const psq=v=>`'${String(v).replace(/'/g,"''")}'`;
const winPs=script=>run('powershell.exe',['-NoProfile','-NonInteractive','-Command',script]);
const WIN_BACKGROUND_EXE=()=>path.join(path.dirname(WIN_EXE()),'mcptoai-agent-background.exe');
const winAgentProcesses=()=>`$exe=${psq(WIN_EXE())};$background=${psq(WIN_BACKGROUND_EXE())};$p=@(Get-CimInstance Win32_Process | Where-Object { ($_.ExecutablePath -eq $exe -or $_.ExecutablePath -eq $background) -and $_.CommandLine -match '(?i)(^|\\s)(connect|supervise)(\\s|$)' })`;
async function winStatus(){const removed=removedStatus();if(removed)return removed;const exe=WIN_EXE(),background=WIN_BACKGROUND_EXE();if(!fs.existsSync(exe)&&!fs.existsSync(background))return {running:false,installed:false,detail:'Device Agent is not installed'};if(!fs.existsSync(exe)||!fs.existsSync(background))return {running:false,installed:true,detail:'Device Agent installation incomplete; use Install / Repair'};const r=await winPs(`${winAgentProcesses()};if($p.Count -gt 0){'RUNNING'}else{'STOPPED'}`);const running=r.ok&&r.stdout.trim()==='RUNNING';return {running,installed:true,detail:running?'Agent is running':'Agent is installed but stopped'}}
async function winStart(){
 if(!fs.existsSync(WIN_EXE())||!fs.existsSync(WIN_BACKGROUND_EXE()))return {ok:false,stderr:'Both Device Agent executables are required. Use Install / Repair.'};
 return winPs(`$task=Get-ScheduledTask -TaskName 'MCPtoAI Agent' -ErrorAction SilentlyContinue;if(-not $task){throw 'Scheduled Task missing. Use Install / Repair.'};Enable-ScheduledTask -TaskName 'MCPtoAI Agent' | Out-Null;Start-ScheduledTask -TaskName 'MCPtoAI Agent';'Agent start requested'`);
}
async function winStop(){
 if(!fs.existsSync(WIN_EXE())&&!fs.existsSync(WIN_BACKGROUND_EXE()))return {ok:true,stdout:'Agent is not installed',stderr:''};
 return winPs(`$task=Get-ScheduledTask -TaskName 'MCPtoAI Agent' -ErrorAction SilentlyContinue;if($task){Disable-ScheduledTask -TaskName 'MCPtoAI Agent' | Out-Null;Stop-ScheduledTask -TaskName 'MCPtoAI Agent' -ErrorAction SilentlyContinue};${winAgentProcesses()};$supervisors=@($p | Where-Object { $_.CommandLine -match '(?i)(^|\\s)supervise(\\s|$)' });$targets=if($supervisors.Count -gt 0){$supervisors}else{$p};foreach($x in $targets){& taskkill.exe /PID $x.ProcessId /T /F 2>$null | Out-Null};'Agent stopped'`);
}

function adapter(){
 if(process.platform==='darwin') return {
  platform:'macOS',
  async status(){const removed=removedStatus();if(removed)return removed;const r=await run('launchctl',['print',MAC_SERVICE()]);return {running:r.ok,installed:r.ok,detail:r.ok?'Agent is running':'Agent is stopped'}},
  async start(){const r=await run('launchctl',['print',MAC_SERVICE()]);if(!r.ok)return {ok:false,stderr:'Device Agent background service is not registered. Use Install / Repair first.'};return run('launchctl',['kickstart',MAC_SERVICE()])},
  async servicePid(){const r=await run('launchctl',['print',MAC_SERVICE()]);if(!r.ok)return null;return parseLaunchdPid(r.stdout)},
  async restart(){const r=await run('launchctl',['print',MAC_SERVICE()]);if(!r.ok)return {ok:false,stderr:'Device Agent background service is not registered. Use Install / Repair first.'};return run('launchctl',['kickstart','-k',MAC_SERVICE()],{timeout:45000})},
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
module.exports={adapter,parseLaunchdPid};
