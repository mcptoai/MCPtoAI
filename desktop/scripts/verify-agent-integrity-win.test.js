'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),os=require('os'),path=require('path');
const {hashTree,verify}=require('./verify-agent-integrity-win');
test('Windows signed payload hash detects tampering',t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'win-agent-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const dir=path.join(root,'agent');fs.mkdirSync(dir);const file=path.join(dir,'mcptoai-agent.exe');fs.writeFileSync(file,'signed binary');
 const metadata=path.join(root,'agent-version.json');fs.writeFileSync(metadata,JSON.stringify({version:'0.2.7',sha256:hashTree(dir)}));
 assert.equal(verify(dir,metadata),hashTree(dir));fs.appendFileSync(file,'tamper');assert.throws(()=>verify(dir,metadata),/integrity mismatch/);
});
