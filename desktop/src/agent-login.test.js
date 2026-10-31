const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {EventEmitter}=require('node:events');
const fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'main.js'),'utf8');
const start=source.indexOf("let pendingPairingUrl='';");
const end=source.indexOf("\nipcMain.handle('agent:action'",start);
assert(start>=0&&end>start);
function setup({stdout='',stderr='',exit=0,reject=false,timeout=false}={}){
 const handlers={}, opened=[], sent=[];
 const child=new EventEmitter();child.stdout=new EventEmitter();child.stderr=new EventEmitter();
 const app={};
 const context={
  ipcMain:{handle:(name,fn)=>handlers[name]=fn},
  installedAgentPath:()=>'/fake-agent',fs:{existsSync:()=>true},
  require:(id)=>id==='child_process'?{spawn:(exe,args,opts)=>{assert.equal(opts.env.PYTHONIOENCODING,'utf-8');assert.equal(opts.windowsHide,true);setImmediate(()=>{if(stdout)child.stdout.emit('data',Buffer.from(stdout));if(stderr)child.stderr.emit('data',Buffer.from(stderr));if(!timeout)child.emit('close',exit)});return child}}:require(id),
  process:{env:{}},
  shell:{openExternal:url=>{opened.push(url);return reject?Promise.reject(Error('no browser')):Promise.resolve()}},
  BrowserWindow:{getAllWindows:()=>[{webContents:{send:(...args)=>sent.push(args)}}]},
  readSettings:()=>({}),writeSettings:()=>{},
  setTimeout:(fn,ms)=>{assert.equal(ms,10000);return timeout?setImmediate(fn):1},clearTimeout:()=>{},
  console,URL,Buffer,setImmediate
 };
 vm.runInNewContext(source.slice(start,end),context);
 return {handlers,opened,sent};
}
test('URL from agent stdout opens browser',async()=>{
 const x=setup({stdout:'Sign in:\n https://auth.example.test/activate?code=ABC\n'});
 const result=await x.handlers['agent:login']();assert.equal(result.ok,true);assert.equal(x.opened.length,1);
});
test('stderr tail reaches renderer with secrets redacted',async()=>{
 const x=setup({stderr:'diagnostic: failed\naccess_token=SECRET123\nUnicodeEncodeError: cp1252\n',exit:1});
 const result=await x.handlers['agent:login']();assert.equal(result.ok,false);assert.match(result.error,/UnicodeEncodeError/);assert.doesNotMatch(result.error,/SECRET123/);
});
test('rejected browser sends manual URL to renderer',async()=>{
 const x=setup({stdout:'https://auth.example.test/activate?code=ABC\n',reject:true});
 await x.handlers['agent:login']();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(x.sent[0][0],'pairing:manual-url');assert.match(x.sent[0][1],/^https:/);
});
test('ten second URL watchdog notifies renderer',async()=>{
 const x=setup({timeout:true});x.handlers['agent:login']();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(x.sent[0][0],'pairing:timeout');
});
