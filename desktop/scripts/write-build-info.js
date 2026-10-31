'use strict';
const fs=require('fs'),path=require('path'),cp=require('child_process');
const root=path.resolve(__dirname,'../..');
function git(...args){return cp.execFileSync('git',args,{cwd:root,encoding:'utf8'}).trim()}
const commit=git('rev-parse','HEAD');
const dirty=Boolean(git('status','--porcelain','--untracked-files=normal'));
if(dirty && process.env.MCPTOAI_RELEASE_BUILD==='1')throw new Error('Release build requires a clean working tree');
const data={commit,dirty,date:cp.execFileSync('git',['show','-s','--format=%cI','HEAD'],{cwd:root,encoding:'utf8'}).trim(),platform:process.platform,arch:process.arch};
for(const target of ['desktop/build-info.json','device-agent/mcptoai_agent/build-info.json']){
 fs.writeFileSync(path.join(root,target),JSON.stringify(data,null,2)+'\n');
}
console.log('Build source',JSON.stringify(data));
