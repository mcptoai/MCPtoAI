'use strict'
// Device-local IPC: socket is in a 0700 user directory and never exposed to
// the renderer or the web relay. The agent validates its #84 grant separately.
const net=require('net'),fs=require('fs'),path=require('path'),os=require('os');
const {requestApprovalAttention}=require('./approval-attention');
const SOCKET=path.join(os.homedir(),'.config','mcptoai','inbound-upload-approval.sock');
function validApprovalSubfolder(relative){
 if(typeof relative!=='string'||relative.length<1||relative.length>240||relative.includes('\\'))return false;
 const parts=relative.split('/');
 const reserved=/^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$/i;
 return parts.length<=16 && parts.every(part=>part.length<=120 && part.length>0 &&
  part!=='.' && part!=='..' && !part.startsWith('~') && !part.endsWith('.') && !part.endsWith(' ') &&
  part===part.normalize('NFC') && !reserved.test(part) && /^[A-Za-z0-9_. -]+$/.test(part));
}
function approvalDetail({name,size,workspace,sha256,create_subfolder,chatImage=false}){
 return `File: ${name}\nSize: ${size.toLocaleString()} bytes\nDestination: ${workspace}${create_subfolder?`\nOluşturulacak klasör: ${create_subfolder}`:''}\nSHA-256: ${sha256.slice(0,16)}…\n\n${chatImage?'Save for the current chat turn. Device tools will request separate permission.':'Approve this transfer only.'}`;
}
function startInboundApproval({dialog,BrowserWindow,Notification}) {
 if(process.platform==='win32')return ()=>{};
 const dir=path.dirname(SOCKET);
 fs.mkdirSync(dir,{recursive:true,mode:0o700});
 if((fs.statSync(dir).mode&0o077)!==0)throw Error('Unsafe approval IPC directory permissions');
 try{fs.unlinkSync(SOCKET)}catch(e){if(e.code!=='ENOENT')throw e}
 const server=net.createServer(socket=>{
  let buf='',done=false;
  socket.setTimeout(65000,()=>socket.destroy());
  socket.on('data',async bytes=>{
   if(done)return;
   buf+=bytes.toString('utf8');
   if(Buffer.byteLength(buf)>4096){done=true;socket.destroy();return}
   if(!buf.includes('\n'))return;
   done=true;
   let request;try{request=JSON.parse(buf.split('\n')[0])}catch{socket.end('{"approved":false}\n');return}
   const {name,size,workspace,sha256,transfer_id,purpose,session_id,turn_id,create_subfolder}=request||{};
   if(typeof name!=='string'||name.length>120||!Number.isSafeInteger(size)||size<1||size>(purpose==='chat_image_save'?10485760:52428800)||
      typeof workspace!=='string'||workspace.length>512||
      (create_subfolder!==undefined&&(purpose!==undefined||!validApprovalSubfolder(create_subfolder)))||!(/^[a-f0-9]{64}$/).test(sha256)||
      typeof transfer_id!=='string'||!(/^[a-f0-9-]{36}$/).test(transfer_id)||
      (purpose!==undefined&&(purpose!=='chat_image_save'||!(/^[a-f0-9-]{36}$/).test(session_id||'')||!(/^[a-f0-9-]{36}$/).test(turn_id||'')))){
      socket.end('{"approved":false}\n');return
   }
   const win=BrowserWindow.getAllWindows().find(w=>!w.isDestroyed());
   if(!win){socket.end('{"approved":false,"reason":"desktop_closed"}\n');return}
   try{
    const chatImage=purpose==='chat_image_save';
    requestApprovalAttention(win,Notification,chatImage?'MCPtoAI — Save chat image':'MCPtoAI — Incoming file');
    const result=await dialog.showMessageBox(win,{type:'warning',title:'MCPtoAI — Incoming file',
      message:chatImage?'Save this chat image on your computer?':'Allow this file to be saved on your computer?',
      detail:approvalDetail({name,size,workspace,sha256,create_subfolder,chatImage}),
      buttons:['Deny','Accept once'],defaultId:0,cancelId:0,noLink:true});
    socket.end(JSON.stringify({approved:result.response===1})+'\n')
   }catch{socket.end('{"approved":false}\n')}
  });
 });
 server.listen(SOCKET,()=>fs.chmodSync(SOCKET,0o600));
 return ()=>{server.close();try{fs.unlinkSync(SOCKET)}catch{}};
}
module.exports={startInboundApproval,approvalDetail,validApprovalSubfolder,SOCKET};
