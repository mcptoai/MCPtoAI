const test=require('node:test');const assert=require('node:assert/strict');const fs=require('fs');const os=require('os');const path=require('path');
const observation=require('../src/activity-observation');
test('last local observation survives restart and clear removes it',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'mcptoai-activity-'));
 try{
  assert.equal(observation.read(dir),null);
  observation.update(dir,[{timestamp_utc:'2026-11-16T12:00:00Z'}]);
  assert.equal(observation.read(dir).timestamp_utc,'2026-11-16T12:00:00Z');
  observation.update(dir,[{timestamp_utc:'2026-11-15T12:00:00Z'}]);
  assert.equal(observation.read(dir).timestamp_utc,'2026-11-16T12:00:00Z');
  observation.clear(dir);assert.equal(observation.read(dir),null);
 }finally{fs.rmSync(dir,{recursive:true,force:true})}
});
