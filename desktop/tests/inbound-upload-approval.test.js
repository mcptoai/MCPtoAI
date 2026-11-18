const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),net=require('net');
const {startInboundApproval,SOCKET}=require('../src/inbound-upload-approval');
function send(frame){return new Promise((resolve,reject)=>{const client=net.connect(SOCKET);let data='';client.on('connect',()=>client.write(JSON.stringify(frame)+'\n'));client.on('data',d=>data+=d);client.on('end',()=>resolve(JSON.parse(data.trim())));client.on('error',reject)})}
const valid={transfer_id:'00000000-0000-4000-8000-000000000001',name:'invoice.pdf',size:3,workspace:'/tmp',sha256:'a'.repeat(64)};
test('main-process approval is local, explicit and rejects missing window',async()=>{
 const stop=startInboundApproval({dialog:{showMessageBox:async()=>({response:1})},BrowserWindow:{getAllWindows:()=>[]}});
 try{
  await new Promise((resolve,reject)=>{const deadline=Date.now()+2000;const poll=()=>fs.existsSync(SOCKET)?resolve():Date.now()>deadline?reject(Error('socket timeout')):setTimeout(poll,10);poll()});
  assert.equal((await send(valid)).approved,false);
  assert.equal((await send({...valid,size:10485761})).approved,false);
  assert.equal(fs.statSync(SOCKET).mode&0o077,0);
 }finally{stop()}
});
