const fs=require('fs'),path=require('path'),os=require('os'),crypto=require('crypto');
const {execFileSync}=require('child_process');
const RUN_KEY='HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run';
const RUN_VALUE='MCPtoAI Agent';
function base(){return process.env.LOCALAPPDATA||path.join(os.homedir(),'AppData','Local')}
function paths(resourcesPath){const root=path.join(base(),'MCPtoAI'),agentDir=path.join(root,'Agent'),exe=path.join(agentDir,'mcptoai-agent.exe'),logs=path.join(root,'Logs');return {root,agentDir,exe,logs,source:path.join(resourcesPath,'agent')}}
function files(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(path.join(dir,e.name)):e.isFile()?[path.join(dir,e.name)]:[]).sort()}
function fileHash(f){return crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex')}
function hashTree(dir){const entries=files(dir).map(f=>`${path.relative(dir,f).split(path.sep).join('/')}\0${fileHash(f)}\0`).join('');return crypto.createHash('sha256').update(entries,'utf8').digest('hex')}
function metadata(resourcesPath){try{return JSON.parse(fs.readFileSync(path.join(resourcesPath,'agent-version.json'),'utf8'))}catch{return {version:'0.0.0'}}}
function psq(v){return `'${String(v).replace(/'/g,"''")}'`}
function stop(exe,log=()=>{}){
 // Stop the supervisor tree FIRST. Otherwise it can respawn connect while
 // the installer is replacing the executable and holding file handles.
 const script=`$ErrorActionPreference='Stop';$exe=${psq(exe)};
 $quiet=Join-Path (Split-Path -Parent $exe) 'mcptoai-agent-background.exe';
 $deadline=(Get-Date).AddSeconds(20);
 do {
   $p=@(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and ([string]::Equals($_.ExecutablePath,$exe,[StringComparison]::OrdinalIgnoreCase) -or [string]::Equals($_.ExecutablePath,$quiet,[StringComparison]::OrdinalIgnoreCase)) });
   $supervisors=@($p | Where-Object { $_.CommandLine -match '(?i)(^|\\s)supervise(\\s|$)' });
   foreach($x in $p){Write-Output ('found PID='+$x.ProcessId+' CommandLine='+$x.CommandLine+' stop_method=' + $(if($x.CommandLine -match '(?i)(^|\\s)supervise(\\s|$)'){'taskkill /PID /T /F'}elseif($supervisors.Count -gt 0){'supervisor taskkill tree / Job Object'}else{'taskkill /PID /T /F'}))}
   foreach($x in $supervisors){
     Write-Output ('stopping PID='+$x.ProcessId+' CommandLine='+$x.CommandLine+' method=taskkill /PID /T /F');
     & taskkill.exe /PID $x.ProcessId /T /F 2>$null | Out-Null
   }
   if($supervisors.Count -eq 0){foreach($x in $p){
     Write-Output ('stopping PID='+$x.ProcessId+' CommandLine='+$x.CommandLine+' method=taskkill /PID /T /F');
     & taskkill.exe /PID $x.ProcessId /T /F 2>$null | Out-Null
   }}
   Start-Sleep -Milliseconds 250
 } while((Get-Date) -lt $deadline -and @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and ([string]::Equals($_.ExecutablePath,$exe,[StringComparison]::OrdinalIgnoreCase) -or [string]::Equals($_.ExecutablePath,$quiet,[StringComparison]::OrdinalIgnoreCase)) }).Count -gt 0);
 $remaining=@(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and ([string]::Equals($_.ExecutablePath,$exe,[StringComparison]::OrdinalIgnoreCase) -or [string]::Equals($_.ExecutablePath,$quiet,[StringComparison]::OrdinalIgnoreCase)) });
 if($remaining.Count -gt 0){throw 'Supervisor/agent processes did not exit'};
 Write-Output 'stop complete: no agent processes remain'`;
 try{const output=execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{encoding:'utf8',stdio:'pipe',timeout:30000});for(const line of output.split(/\r?\n/)){if(line.trim())log('Windows agent upgrade: '+line)}}
 catch(e){log('Windows agent upgrade: stop failed '+e.message);throw e}
}
function removeLegacyTask(){try{execFileSync('schtasks.exe',['/Delete','/F','/TN','MCPtoAI Agent'],{stdio:'ignore'})}catch{}}
function backgroundExe(exe){const quiet=path.join(path.dirname(exe),'mcptoai-agent-background.exe');if(!fs.existsSync(quiet))throw new Error('Background supervisor executable missing');return quiet}
function installRestartTask(exe){
 exe=backgroundExe(exe);
 // Task Scheduler owns restart-on-failure. Do not also register the Run key.
 const script=`$ErrorActionPreference='Stop';$name='MCPtoAI Agent';$exe=${psq(exe)};
 $user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;
 $action=New-ScheduledTaskAction -Execute $exe -Argument 'supervise';
 $logon=New-ScheduledTaskTrigger -AtLogOn -User $user;
 # A registration-time time trigger starts repetition in the current session.
 # A daily midnight trigger can defer repetition until the next session/day.
 $periodic=New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(15);
 $periodic.Repetition=New-CimInstance -ClientOnly -Namespace Root/Microsoft/Windows/TaskScheduler -ClassName MSFT_TaskRepetitionPattern -Property @{Interval='PT5M';StopAtDurationEnd=$false};
 $trigger=@($logon,$periodic);
 $settings=New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;
 $principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited;
 Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null;
 $task=Get-ScheduledTask -TaskName $name;
 if($task.Settings.RestartCount -lt 1){throw 'Task restart policy missing'};
 if($task.Settings.MultipleInstances -ne 'IgnoreNew'){throw 'Multiple-instance policy missing'};
 if(-not @($task.Triggers | Where-Object {$_.Repetition.Interval -eq 'PT5M' -and -not $_.Repetition.Duration -and $_.StartBoundary}).Count){throw 'registration-time indefinite 5-minute trigger missing'};
 Start-ScheduledTask -TaskName $name`;
 execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{encoding:'utf8',timeout:30000,stdio:'pipe'});
 // Remove legacy Run ONLY after the restartable task has been registered.
 // Missing value is fine; failure to delete an existing value is NOT fine:
 // otherwise both Task Scheduler and Run may launch supervisors at logon.
 let exists=false;
 try{execFileSync('reg.exe',['QUERY',RUN_KEY,'/v',RUN_VALUE],{stdio:'ignore'});exists=true}catch{}
 if(exists){
   execFileSync('reg.exe',['DELETE',RUN_KEY,'/v',RUN_VALUE,'/f'],{stdio:'pipe'});
   try{execFileSync('reg.exe',['QUERY',RUN_KEY,'/v',RUN_VALUE],{stdio:'ignore'});throw new Error('Legacy Run value still exists after removal')}catch(e){if(e.message.includes('Legacy Run value'))throw e}
 }
}
function health(exe){execFileSync(exe,['--help'],{stdio:'ignore',timeout:15000})}
function installedMeta(resourcesPath){const f=path.join(paths(resourcesPath).agentDir,'version.json');try{return JSON.parse(fs.readFileSync(f,'utf8'))}catch{return null}}
function installedVersion(resourcesPath){const m=installedMeta(resourcesPath);return (m&&m.version)||null}
function versionParts(v){return String(v||'0').split('.').map(x=>parseInt(x,10)||0)}
function compareVersions(a,b){const aa=versionParts(a),bb=versionParts(b),n=Math.max(aa.length,bb.length);for(let i=0;i<n;i++){const d=(aa[i]||0)-(bb[i]||0);if(d)return d>0?1:-1}return 0}
// Güncelleme: daha yeni sürüm numarası VEYA aynı sürüm numarasıyla yeniden derlenmiş agent
// (paketteki özet kurulu olandan farklı). Kurulu özet version.json'dan okunur; 1128 dosya her
// açılışta yeniden okunmaz. Eski bir sürüme asla geri dönülmez.
function status(resourcesPath){const im=installedMeta(resourcesPath),installed=(im&&im.version)||null,meta=metadata(resourcesPath),bundled=meta.version;const cmp=installed?compareVersions(bundled,installed):0;const rebuilt=!!installed&&cmp===0&&!!meta.sha256&&!!(im&&im.sha256)&&im.sha256!==meta.sha256;return {installed,bundled,rebuilt,updateAvailable:(!installed&&fs.existsSync(paths(resourcesPath).exe))||!!installed&&(cmp>0||rebuilt)}}
function install(resourcesPath,log=()=>{}){const p=paths(resourcesPath),meta=metadata(resourcesPath),sourceExe=path.join(p.source,'mcptoai-agent.exe'),backup=`${p.agentDir}.backup`;try{if(!fs.existsSync(sourceExe))throw new Error('Bundled Windows Device Agent is missing.');if(!fs.existsSync(path.join(p.source,'mcptoai-agent-background.exe')))throw new Error('Bundled Windows background agent is missing.');const actual=hashTree(p.source);if(meta.sha256&&actual!==meta.sha256)throw new Error('Bundled Windows Device Agent integrity check failed.');removeLegacyTask();stop(p.exe,log);fs.mkdirSync(p.root,{recursive:true});fs.mkdirSync(p.logs,{recursive:true});fs.rmSync(backup,{recursive:true,force:true});if(fs.existsSync(p.agentDir))fs.renameSync(p.agentDir,backup);try{fs.cpSync(p.source,p.agentDir,{recursive:true});fs.writeFileSync(path.join(p.agentDir,'version.json'),JSON.stringify({version:meta.version,sha256:actual},null,2));health(p.exe);health(backgroundExe(p.exe));installRestartTask(p.exe);fs.rmSync(backup,{recursive:true,force:true});return {ok:true,version:meta.version,sha256:actual,agent_dir:p.agentDir}}catch(e){stop(p.exe);fs.rmSync(p.agentDir,{recursive:true,force:true});if(fs.existsSync(backup)){fs.renameSync(backup,p.agentDir);try{health(p.exe);health(backgroundExe(p.exe));installRestartTask(p.exe)}catch{}}throw e}}catch(e){return {ok:false,error:e.message}}}
function upgradeIfNeeded(resourcesPath,log=()=>{}){const s=status(resourcesPath);if(!s.installed||!s.updateAvailable)return {ok:true,updated:false,...s};const r=install(resourcesPath,log);return {...r,updated:!!r.ok,installed:r.ok?r.version:s.installed,bundled:s.bundled}}
module.exports={install,status,paths,hashTree,compareVersions,upgradeIfNeeded};
