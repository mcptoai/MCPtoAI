'use strict';
// Windows writer uses per-file SHA-256 digests, unlike the macOS raw-byte tree.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
function hashTree(dir){
 const walk=d=>fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(path.join(d,e.name)):e.isFile()?[path.join(d,e.name)]:[]).sort();
 const files=walk(dir);if(!files.length)throw new Error('Empty Windows agent payload');
 const records=files.map(f=>`${path.relative(dir,f).split(path.sep).join('/')}\0${crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex')}\0`).join('');
 return crypto.createHash('sha256').update(records,'utf8').digest('hex');
}
function verify(dir,metaPath){const meta=JSON.parse(fs.readFileSync(metaPath,'utf8'));const actual=hashTree(dir);if(!/^[a-f0-9]{64}$/.test(meta.sha256||'')||meta.sha256!==actual)throw new Error(`Windows agent integrity mismatch: ${actual}`);return actual}
if(require.main===module){try{console.log(verify(process.argv[2]||path.resolve(__dirname,'../../device-agent/dist/mcptoai-agent'),process.argv[3]||path.resolve(__dirname,'../agent-version.json')))}catch(e){console.error(e.message);process.exitCode=1}}
module.exports={hashTree,verify};
