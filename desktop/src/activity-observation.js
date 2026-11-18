'use strict';
const fs=require('fs');const path=require('path');
const FILE='activity-last-observed.json';
function valid(value){
 if(!value||typeof value.timestamp_utc!=='string'||!Number.isFinite(Date.parse(value.timestamp_utc)))return false;
 return value.source==='device-local Activity';
}
function read(root){try{const v=JSON.parse(fs.readFileSync(path.join(root,FILE),'utf8'));return valid(v)?v:null}catch{return null}}
function update(root,events){
 const latest=(Array.isArray(events)?events:[]).filter(e=>e&&Number.isFinite(Date.parse(e.timestamp_utc))).sort((a,b)=>Date.parse(b.timestamp_utc)-Date.parse(a.timestamp_utc))[0];
 if(!latest)return read(root);
 const previous=read(root),candidate={timestamp_utc:latest.timestamp_utc,source:'device-local Activity'};
 if(previous&&Date.parse(previous.timestamp_utc)>=Date.parse(candidate.timestamp_utc))return previous;
 fs.mkdirSync(root,{recursive:true});const target=path.join(root,FILE),tmp=target+'.'+process.pid+'.tmp';
 try{fs.writeFileSync(tmp,JSON.stringify(candidate),{mode:0o600,flag:'wx'});fs.renameSync(tmp,target)}finally{try{fs.unlinkSync(tmp)}catch{}}
 return candidate;
}
function clear(root){try{fs.unlinkSync(path.join(root,FILE))}catch(e){if(e.code!=='ENOENT')throw e}}
module.exports={read,update,clear};
