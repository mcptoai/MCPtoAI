'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),os=require('os'),path=require('path');
const {createDesktopLogger}=require('./desktop-file-log');
test('Windows APPDATA persistent handover and errors rotate',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'mcptoai-a1-'));
 try{const log=createDesktopLogger({platform:'win32',configRoot:root,home:root,maxBytes:180,backups:2});
 log.handover('Windows install then handover');log.error('failed %s','fixture');
 assert.match(fs.readFileSync(path.join(root,'logs','desktop-handover.log'),'utf8'),/Windows install then handover/);
 assert.match(fs.readFileSync(path.join(root,'logs','desktop-error.log'),'utf8'),/failed fixture/);
 for(let i=0;i<50;i++)log.error('error-'+i);
 assert.ok(fs.existsSync(path.join(root,'logs','desktop-error.log.1')));
 assert.ok(fs.statSync(path.join(root,'logs','desktop-error.log')).size<=180);
 assert.equal(fs.existsSync(path.join(root,'logs','desktop-error.log.3')),false);
 }finally{fs.rmSync(root,{recursive:true,force:true})}
});
test('macOS handover and errors write to Library Logs',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'mcptoai-a1-mac-'));
 try{const log=createDesktopLogger({platform:'darwin',configRoot:root,home:root});log.handover('launchctl fixture');log.error('mac fixture');
 assert.match(fs.readFileSync(path.join(root,'Library','Logs','MCPtoAI','desktop-handover.log'),'utf8'),/launchctl fixture/);
 assert.match(fs.readFileSync(path.join(root,'Library','Logs','MCPtoAI','desktop-error.log'),'utf8'),/mac fixture/);
 }finally{fs.rmSync(root,{recursive:true,force:true})}
});
