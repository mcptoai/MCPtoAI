const fs=require('fs'),path=require('path'),os=require('os'),crypto=require('crypto');
const {execFileSync,spawn}=require('child_process');
const RUN_KEY='HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run';
const RUN_VALUE='MCPtoAI Agent';
function base(){return process.env.LOCALAPPDATA||path.join(os.homedir(),'AppData','Local')}
function paths(resourcesPath){const root=path.join(base(),'MCPtoAI'),agentDir=path.join(root,'Agent'),exe=path.join(agentDir,'mcptoai-agent.exe'),logs=path.join(root,'Logs');return {root,agentDir,exe,logs,source:path.join(resourcesPath,'agent')}}
function files(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(path.join(dir,e.name)):e.isFile()?[path.join(dir,e.name)]:[]).sort()}
function fileHash(f){return crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex')}
function hashTree(dir){const entries=files(dir).map(f=>`${path.relative(dir,f).split(path.sep).join('/')}\0${fileHash(f)}\0`).join('');return crypto.createHash('sha256').update(entries,'utf8').digest('hex')}
function metadata(resourcesPath){try{return JSON.parse(fs.readFileSync(path.join(resourcesPath,'agent-version.json'),'utf8'))}catch{return {version:'0.0.0'}}}
function psq(v){return `'${String(v).replace(/'/g,"''")}'`}
function stop(exe){try{const script=`$exe=${psq(exe)};$p=Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $exe -and $_.CommandLine -match '(?i)(^|\\s)connect(\\s|$)' };foreach($x in $p){Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue}`;execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{stdio:'ignore'})}catch{}}
function removeLegacyTask(){try{execFileSync('schtasks.exe',['/Delete','/F','/TN','MCPtoAI Agent'],{stdio:'ignore'})}catch{}}
function autostart(exe){const cmd=`"${exe}" connect`;execFileSync('reg.exe',['ADD',RUN_KEY,'/v',RUN_VALUE,'/t','REG_SZ','/d',cmd,'/f'],{stdio:'ignore'})}
function start(exe){const child=spawn(exe,['connect'],{detached:true,windowsHide:true,stdio:'ignore'});child.unref()}
function health(exe){execFileSync(exe,['--help'],{stdio:'ignore',timeout:15000})}
function installedMeta(resourcesPath){const f=path.join(paths(resourcesPath).agentDir,'version.json');try{return JSON.parse(fs.readFileSync(f,'utf8'))}catch{return null}}
function installedVersion(resourcesPath){const m=installedMeta(resourcesPath);return (m&&m.version)||null}
function versionParts(v){return String(v||'0').split('.').map(x=>parseInt(x,10)||0)}
function compareVersions(a,b){const aa=versionParts(a),bb=versionParts(b),n=Math.max(aa.length,bb.length);for(let i=0;i<n;i++){const d=(aa[i]||0)-(bb[i]||0);if(d)return d>0?1:-1}return 0}
// Güncelleme: daha yeni sürüm numarası VEYA aynı sürüm numarasıyla yeniden derlenmiş agent
// (paketteki özet kurulu olandan farklı). Kurulu özet version.json'dan okunur; 1128 dosya her
// açılışta yeniden okunmaz. Eski bir sürüme asla geri dönülmez.
function status(resourcesPath){const im=installedMeta(resourcesPath),installed=(im&&im.version)||null,meta=metadata(resourcesPath),bundled=meta.version;const cmp=installed?compareVersions(bundled,installed):0;const rebuilt=!!installed&&cmp===0&&!!meta.sha256&&!!(im&&im.sha256)&&im.sha256!==meta.sha256;return {installed,bundled,rebuilt,updateAvailable:!!installed&&(cmp>0||rebuilt)}}
function install(resourcesPath){const p=paths(resourcesPath),meta=metadata(resourcesPath),sourceExe=path.join(p.source,'mcptoai-agent.exe'),backup=`${p.agentDir}.backup`;try{if(!fs.existsSync(sourceExe))throw new Error('Bundled Windows Device Agent is missing.');const actual=hashTree(p.source);if(meta.sha256&&actual!==meta.sha256)throw new Error('Bundled Windows Device Agent integrity check failed.');stop(p.exe);removeLegacyTask();fs.mkdirSync(p.root,{recursive:true});fs.mkdirSync(p.logs,{recursive:true});fs.rmSync(backup,{recursive:true,force:true});if(fs.existsSync(p.agentDir))fs.renameSync(p.agentDir,backup);try{fs.cpSync(p.source,p.agentDir,{recursive:true});fs.writeFileSync(path.join(p.agentDir,'version.json'),JSON.stringify({version:meta.version,sha256:actual},null,2));health(p.exe);autostart(p.exe);start(p.exe);fs.rmSync(backup,{recursive:true,force:true});return {ok:true,version:meta.version,sha256:actual,agent_dir:p.agentDir}}catch(e){stop(p.exe);fs.rmSync(p.agentDir,{recursive:true,force:true});if(fs.existsSync(backup)){fs.renameSync(backup,p.agentDir);try{health(p.exe);autostart(p.exe);start(p.exe)}catch{}}throw e}}catch(e){return {ok:false,error:e.message}}}
function upgradeIfNeeded(resourcesPath){const s=status(resourcesPath);if(!s.installed||!s.updateAvailable)return {ok:true,updated:false,...s};const r=install(resourcesPath);return {...r,updated:!!r.ok,installed:r.ok?r.version:s.installed,bundled:s.bundled}}
module.exports={install,status,paths,hashTree,compareVersions,upgradeIfNeeded};
