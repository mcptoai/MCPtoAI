'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),os=require('os'),path=require('path'),crypto=require('crypto'),yaml=require('js-yaml');
const {verify}=require('./verify-updater-artifacts');
test('manifest checks payload hash, size, blockmap, missing files and version',t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'updater-verify-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const file='MCPtoAI-0.2.7-x64-Setup.exe',bytes=Buffer.from('installer');
 const meta={version:'0.2.7',files:[{url:file,size:bytes.length,sha512:crypto.createHash('sha512').update(bytes).digest('base64')}],path:file};meta.sha512=meta.files[0].sha512;
 const save=()=>fs.writeFileSync(path.join(dir,'latest.yml'),yaml.dump(meta));
 fs.writeFileSync(path.join(dir,file),bytes);fs.writeFileSync(path.join(dir,file+'.blockmap'),'blockmap');save();
 assert.equal(verify(dir,'latest.yml','0.2.7','.exe'),1);
 assert.throws(()=>verify(dir,'latest.yml','0.2.8','.exe'),/version mismatch/);
 fs.writeFileSync(path.join(dir,file),'tampered!');assert.throws(()=>verify(dir,'latest.yml','0.2.7','.exe'),/SHA-512 mismatch/);
 fs.writeFileSync(path.join(dir,file),bytes);fs.rmSync(path.join(dir,file+'.blockmap'));assert.throws(()=>verify(dir,'latest.yml','0.2.7','.exe'),/ENOENT/);
});
