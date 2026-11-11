'use strict';
const fs=require('fs'),path=require('path'),util=require('util');
function createDesktopLogger({platform,configRoot,home,maxBytes=1024*1024,backups=3}){
 const dir=platform==='win32'?path.join(configRoot,'logs'):path.join(home,'Library','Logs','MCPtoAI');
 function append(name,message){try{
   fs.mkdirSync(dir,{recursive:true,mode:0o700});const file=path.join(dir,name);
   const line=new Date().toISOString()+' pid='+process.pid+' '+String(message).replace(/[\r\n]+/g,' ')+'\n';
   if(fs.existsSync(file)&&fs.statSync(file).size+Buffer.byteLength(line)>maxBytes){
     fs.rmSync(file+'.'+backups,{force:true});
     for(let i=backups-1;i>=1;i--)if(fs.existsSync(file+'.'+i))fs.renameSync(file+'.'+i,file+'.'+(i+1));
     fs.renameSync(file,file+'.1');
   }
   fs.appendFileSync(file,line,{mode:0o600});
 }catch{/* logging must not break application startup */}}
 return {handover:message=>append('desktop-handover.log',message),error:(...args)=>append('desktop-error.log',util.format(...args)),dir};
}
module.exports={createDesktopLogger};
