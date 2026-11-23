'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {approvalDetail,validApprovalSubfolder}=require('./inbound-upload-approval');
test('native approval includes explicit folder creation and bound file digest',()=>{
 const details=approvalDetail({name:'IMG_2026.HEIC',size:49*1024*1024,
   workspace:'/Users/Tester/Documents',create_subfolder:'Heictest',sha256:'a'.repeat(64)});
 assert.match(details,/Oluşturulacak klasör: Heictest/);
 assert.match(details,/IMG_2026\.HEIC/);
 assert.match(details,/51,380,224 bytes/);
 assert.match(details,/SHA-256: a{16}…/);
 assert.match(details,/Approve this transfer only/);
});
test('native approval for existing folder does not promise creation',()=>{
 const details=approvalDetail({name:'sample.txt',size:3,
   workspace:'/Users/Tester/Documents/Existing',sha256:'b'.repeat(64)});
 assert.doesNotMatch(details,/Oluşturulacak klasör/);
});

test('native IPC accepts bounded relative folder intent only',()=>{
 for(const safe of ['Heictest','Reports/2026/Heictest'])assert.equal(validApprovalSubfolder(safe),true);
 for(const unsafe of ['../outside','/absolute','C:/bad','a\\b','CON','PRN.txt','COM1','a//b','x/' .repeat(16)+'last', 'bad.','bad '])
   assert.equal(validApprovalSubfolder(unsafe),false,unsafe);
});
