'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto');
function hashTree(dir){
  if(!fs.statSync(dir).isDirectory())throw new Error(`Not a directory: ${dir}`);
  const walk=d=>fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(path.join(d,e.name)):e.isFile()?[path.join(d,e.name)]:[]).sort();
  const files=walk(dir);if(!files.length)throw new Error(`Empty agent directory: ${dir}`);
  const h=crypto.createHash('sha256');
  for(const f of files){h.update(path.relative(dir,f));h.update('\0');h.update(fs.readFileSync(f));h.update('\0')}
  return h.digest('hex');
}
function verify(dir,metadata){
  const meta=JSON.parse(fs.readFileSync(metadata,'utf8'));
  if(!/^\d+\.\d+\.\d+/.test(meta.version||''))throw new Error('Invalid agent version');
  if(!/^[a-f0-9]{64}$/.test(meta.sha256||''))throw new Error('Invalid agent SHA-256');
  const actual=hashTree(dir);
  if(actual!==meta.sha256)throw new Error(`Agent integrity mismatch: expected ${meta.sha256}, got ${actual}`);
  return {version:meta.version,sha256:actual};
}
if(require.main===module){try{const [dir,meta]=process.argv.slice(2);if(!dir||!meta)throw new Error('Usage: node verify-agent-integrity.js AGENT_DIR AGENT_VERSION_JSON');console.log(JSON.stringify(verify(dir,meta)))}catch(e){console.error(e.message);process.exitCode=1}}
module.exports={hashTree,verify};
