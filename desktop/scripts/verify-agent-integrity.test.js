'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),os=require('os'),path=require('path');
const {hashTree,verify}=require('./verify-agent-integrity');
test('signed-tree metadata matches and detects mutation, missing and empty payloads',t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'agent-integrity-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const dir=path.join(root,'agent'),meta=path.join(root,'agent-version.json');fs.mkdirSync(dir);
 assert.throws(()=>hashTree(dir),/Empty agent/);
 fs.writeFileSync(path.join(dir,'agent'),'signed payload');fs.writeFileSync(meta,JSON.stringify({version:'0.2.7',sha256:hashTree(dir)}));
 assert.equal(verify(dir,meta).version,'0.2.7');
 fs.writeFileSync(path.join(dir,'agent'),'modified payload');assert.throws(()=>verify(dir,meta),/integrity mismatch/);
 fs.rmSync(dir,{recursive:true});assert.throws(()=>verify(dir,meta),/ENOENT/);
});
