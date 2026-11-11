'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const yaml=require('js-yaml');
function verify(dist,manifestName,expectedVersion,expectedExtension){
 const manifestPath=path.join(dist,manifestName);
 const manifest=yaml.load(fs.readFileSync(manifestPath,'utf8'));
 if(manifest.version!==expectedVersion)throw new Error(`Manifest version mismatch: ${manifest.version}`);
 if(!Array.isArray(manifest.files)||!manifest.files.length)throw new Error('Missing updater files');
 for(const entry of manifest.files){
  if(typeof entry.url!=='string'||!entry.url.endsWith(expectedExtension)||path.basename(entry.url)!==entry.url)throw new Error(`Unexpected updater artifact: ${entry.url}`);
  const file=path.join(dist,entry.url),stat=fs.statSync(file);
  if(!stat.isFile()||!stat.size||stat.size!==entry.size)throw new Error(`Artifact size mismatch: ${entry.url}`);
  const digest=crypto.createHash('sha512').update(fs.readFileSync(file)).digest('base64');
  if(digest!==entry.sha512)throw new Error(`Artifact SHA-512 mismatch: ${entry.url}`);
  const blockmap=file+'.blockmap';if(!fs.statSync(blockmap).size)throw new Error(`Empty blockmap: ${blockmap}`);
 }
 if(manifest.path && !manifest.files.some(f=>f.url===manifest.path&&f.sha512===manifest.sha512))throw new Error('Top-level updater path/hash mismatch');
 return manifest.files.length;
}
if(require.main===module){try{const [dist,manifest,version,extension]=process.argv.slice(2);if(!dist||!manifest||!version||!extension)throw new Error('Usage: verify-updater-artifacts.js DIST MANIFEST VERSION EXTENSION');console.log(`Verified ${verify(dist,manifest,version,extension)} updater artifact(s)`)}catch(e){console.error(e.message);process.exitCode=1}}
module.exports={verify};
