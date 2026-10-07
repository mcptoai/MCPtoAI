// Windows agent güncelleme kararı testleri (dosya sistemi üzerinde, her platformda çalışır).
// Çalıştırma: node src/agent-install-windows.test.js
const assert=require('assert'),fs=require('fs'),os=require('os'),path=require('path');
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'mcptoai-agent-upd-'));
process.env.LOCALAPPDATA=tmp; // kurulu agent'ın aranacağı kök (base())
const m=require('./agent-install-windows.js');
const res=path.join(tmp,'resources');fs.mkdirSync(res,{recursive:true});
const agentDir=m.paths(res).agentDir;fs.mkdirSync(agentDir,{recursive:true});
function set(bundled,installed){
  fs.writeFileSync(path.join(res,'agent-version.json'),JSON.stringify(bundled));
  if(installed)fs.writeFileSync(path.join(agentDir,'version.json'),JSON.stringify(installed));else fs.rmSync(path.join(agentDir,'version.json'),{force:true});
  return m.status(res);
}
try{
  assert.equal(set({version:'0.1.5',sha256:'b'},{version:'0.1.5',sha256:'a'}).updateAvailable,true,'aynı sürüm, farklı özet: yeniden kurulmalı');
  assert.equal(set({version:'0.1.5',sha256:'a'},{version:'0.1.5',sha256:'a'}).updateAvailable,false,'aynı derleme: kurulmamalı');
  assert.equal(set({version:'0.1.6',sha256:'a'},{version:'0.1.5',sha256:'a'}).updateAvailable,true,'yeni sürüm: kurulmalı');
  assert.equal(set({version:'0.1.4',sha256:'z'},{version:'0.1.5',sha256:'a'}).updateAvailable,false,'eski sürüme geri dönülmemeli');
  assert.equal(set({version:'0.1.5',sha256:'b'},{version:'0.1.5'}).updateAvailable,false,'kurulu özet bilinmiyorsa aynı sürüm yeniden kurulmaz');
  assert.equal(set({version:'0.1.5',sha256:'b'},null).updateAvailable,false,'hiç kurulmamışsa güncelleme değil ilk kurulum akışı');
  console.log('agent-install-windows status: 6/6 OK');
}finally{fs.rmSync(tmp,{recursive:true,force:true})}
