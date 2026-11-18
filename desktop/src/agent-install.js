const fs=require('fs'),path=require('path'),os=require('os'),crypto=require('crypto');
const {execFileSync}=require('./hidden-child-process');
const LABEL='com.bkty.mcptoai.device-agent';
function paths(resourcesPath){
  const contents=path.resolve(resourcesPath,'..');
  const sourceBundle=path.join(contents,'Library','LoginItems','MCPtoAI Device Agent.app');
  const source=path.join(sourceBundle,'Contents','Resources','agent');
  const exe=path.join(source,'mcptoai-agent');
  const launcher=path.join(sourceBundle,'Contents','MacOS','mcptoai-device-agent');
  const helper=path.join(sourceBundle,'Contents','Resources','permission-helper');
  const legacyRuntime=path.join(os.homedir(),'Applications','MCPtoAI Device Agent.app');
  const legacyPlist=path.join(os.homedir(),'Library','LaunchAgents',`${LABEL}.plist`);
  return {contents,sourceBundle,source,exe,launcher,helper,legacyRuntime,legacyPlist};
}
function hashTree(dir){const h=crypto.createHash('sha256');const walk=d=>fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(path.join(d,e.name)):e.isFile()?[path.join(d,e.name)]:[]).sort();for(const f of walk(dir)){h.update(path.relative(dir,f));h.update('\0');h.update(fs.readFileSync(f));h.update('\0')}return h.digest('hex')}
function bundledVersion(resourcesPath){try{return JSON.parse(fs.readFileSync(path.join(resourcesPath,'agent-version.json'),'utf8')).version||'0.0.0'}catch{return '0.0.0'}}
function plistVersion(bundle){try{return JSON.parse(execFileSync('/usr/bin/plutil',['-convert','json','-o','-',path.join(bundle,'Contents','Info.plist')],{encoding:'utf8'})).CFBundleShortVersionString||null}catch{return null}}
function installedVersion(resourcesPath){const p=paths(resourcesPath);return fs.existsSync(p.legacyRuntime)?plistVersion(p.legacyRuntime):plistVersion(p.sourceBundle)}
function verifySource(p,resourcesPath){
  if(!fs.existsSync(p.sourceBundle))throw new Error('Bundled Device Agent login item is missing.');
  if(!fs.existsSync(p.exe)||!fs.existsSync(p.launcher))throw new Error('Bundled Device Agent runtime is incomplete.');
  if(process.platform==='darwin'&&process.env.MCPTOAI_ALLOW_UNSIGNED_AGENT!=='1'){
    try{execFileSync('/usr/bin/codesign',['--verify','--deep','--strict','--verbose=2',p.sourceBundle],{stdio:'ignore'})}
    catch{if(!process.defaultApp)throw new Error('Bundled Device Agent login item signature verification failed.')}
  }
  const actual=hashTree(p.source);let expected='';
  try{expected=JSON.parse(fs.readFileSync(path.join(resourcesPath,'agent-version.json'),'utf8')).sha256||''}catch{}
  if(expected&&actual!==expected)throw new Error('Bundled Device Agent integrity check failed.');
  return {sha256:actual};
}
function removeLegacy(p){
  if(fs.existsSync(p.legacyPlist)){
    try{execFileSync('launchctl',['bootout',`gui/${process.getuid()}/${LABEL}`],{stdio:'ignore'})}catch{}
    try{fs.rmSync(p.legacyPlist,{force:true})}catch{}
  }
  try{fs.rmSync(p.legacyRuntime,{recursive:true,force:true})}catch{}
}
function install(resourcesPath){
  if(process.platform!=='darwin')return {ok:true};
  try{
    const p=paths(resourcesPath),verified=verifySource(p,resourcesPath);
    removeLegacy(p);
    return {ok:true,agent_app:p.sourceBundle,version:bundledVersion(resourcesPath),sha256:verified.sha256,modern_login_item:true};
  }catch(e){return {ok:false,error:e.message}}
}
// Associate legacy launchd background activity with the Desktop bundle.
// Only a changed plist may cause a reload. launchd bootout completes asynchronously.
const launchctlGone = ({run,service,timeoutMs=6000,pollMs=150,clock=Date.now,wait=ms=>{const view=new Int32Array(new SharedArrayBuffer(4));Atomics.wait(view,0,0,ms)}}) => {
  const deadline=clock()+timeoutMs;
  for (;;) {
    try {run('/bin/launchctl',['print',service],{encoding:'utf8',timeout:2000})}
    catch {return true}
    if(clock()>=deadline)return false;
    wait(pollMs);
  }
};
function repairLegacyPlist({plist=paths(process.resourcesPath).legacyPlist,run=execFileSync,waitForGone=launchctlGone,wait=ms=>{const view=new Int32Array(new SharedArrayBuffer(4));Atomics.wait(view,0,0,ms)}}={}){
  if(process.platform!=='darwin'||!fs.existsSync(plist))return {ok:true,changed:false};
  const key='AssociatedBundleIdentifiers',identifier='com.bkty.mcptoai.desktop';
  try{
    const current=JSON.parse(run('/usr/bin/plutil',['-convert','json','-o','-',plist],{encoding:'utf8'}));
    const unchanged=Array.isArray(current[key])&&current[key].length===1&&current[key][0]===identifier;
    const service=`gui/${process.getuid()}`,target=`${service}/${LABEL}`;
    if(unchanged){
      // A prior failed bootstrap may have left a correct plist but NO service.
      // Starting an absent service is safe and is not a restart of a running agent.
      try {run('/bin/launchctl',['print',target],{encoding:'utf8',timeout:2000});return {ok:true,changed:false}}
      catch {}
    }
    if(!unchanged){
    const updated={...current,[key]:[identifier]};
    const temp=plist+'.'+process.pid+'.tmp';
    try{
      fs.writeFileSync(temp,JSON.stringify(updated),{mode:0o600});
      run('/usr/bin/plutil',['-convert','xml1','-o',temp,temp]);
      fs.renameSync(temp,plist);
    }finally{try{fs.unlinkSync(temp)}catch{}}
    }
    let registered=false;
    try{run('/bin/launchctl',['print',target],{encoding:'utf8',timeout:2000});registered=true}catch{}
    if(!unchanged&&registered){
      run('/bin/launchctl',['bootout',target],{timeout:8000});
      if(!waitForGone({run,service:target}))return {ok:false,changed:!unchanged,error:'LaunchAgent still registered after bootout timeout'};
    }
    let error;
    for(let attempt=1;attempt<=2;attempt++){
      try {
        run('/bin/launchctl',['bootstrap',service,plist],{timeout:8000});
        return {ok:true,changed:!unchanged,reloaded:!unchanged,started:true,attempts:attempt};
      } catch(e) {
        error=e;
        // Do not assume error 5 always means a race: check if launchd did register.
        try {run('/bin/launchctl',['print',target],{timeout:2000});return {ok:true,changed:!unchanged,reloaded:!unchanged,started:true,attempts:attempt,alreadyRegistered:true}}
        catch {}
        if(attempt===1){if(!waitForGone({run,service:target}))return {ok:false,changed:!unchanged,error:'LaunchAgent still registered after bootstrap failure'};wait(250)}
      }
    }
    return {ok:false,changed:!unchanged,error:'LaunchAgent bootstrap failed after two attempts: '+String(error?.stderr||error?.message||error)};
  }catch(e){return {ok:false,error:e.message,changed:true}}
}
function versionParts(v){return String(v||'0').split('.').map(x=>parseInt(x,10)||0)}
function compareVersions(a,b){const aa=versionParts(a),bb=versionParts(b),n=Math.max(aa.length,bb.length);for(let i=0;i<n;i++){const d=(aa[i]||0)-(bb[i]||0);if(d)return d>0?1:-1}return 0}
function status(resourcesPath){
  const p=paths(resourcesPath),bundled=bundledVersion(resourcesPath),legacy=fs.existsSync(p.legacyRuntime)?plistVersion(p.legacyRuntime):null;
  let expected='',bundledHash='';try{expected=JSON.parse(fs.readFileSync(path.join(resourcesPath,'agent-version.json'),'utf8')).sha256||''}catch{}try{if(fs.existsSync(p.source))bundledHash=hashTree(p.source)}catch{}
  const installed=legacy||plistVersion(p.sourceBundle);const cmp=legacy?compareVersions(bundled,legacy):0;
  const integrityMismatch=!!expected&&!!bundledHash&&expected!==bundledHash;
  return {installed,bundled,installedHash:bundledHash,expectedHash:expected,integrityMismatch,updateAvailable:!!legacy&&(cmp>0||integrityMismatch),legacyInstalled:!!legacy,modernLoginItem:fs.existsSync(p.sourceBundle)};
}
function upgradeIfNeeded(resourcesPath){const s=status(resourcesPath);if(!s.legacyInstalled&&!s.integrityMismatch)return {ok:true,updated:false,...s};const r=install(resourcesPath);return {...r,updated:!!r.ok,installed:r.ok?r.version:s.installed,bundled:s.bundled}}
module.exports={install,paths,status,bundledVersion,installedVersion,hashTree,compareVersions,upgradeIfNeeded,repairLegacyPlist,launchctlGone};
