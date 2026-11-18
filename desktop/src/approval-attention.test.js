'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {requestApprovalAttention}=require('./approval-attention');
test('restores, shows and focuses before notification',()=>{
  const calls=[];
  const win={isDestroyed:()=>false,isMinimized:()=>true,isVisible:()=>false,
    restore:()=>calls.push('restore'),show:()=>calls.push('show'),focus:()=>calls.push('focus')};
  class Notification {static isSupported(){return true} constructor(opts){assert.equal(opts.title,'MCPtoAI')} show(){calls.push('notify')}}
  assert.equal(requestApprovalAttention(win,Notification,'MCPtoAI'),true);
  assert.deepEqual(calls,['restore','show','focus','notify']);
});
test('closed window fails closed without notification',()=>{
  assert.equal(requestApprovalAttention({isDestroyed:()=>true},null,'MCPtoAI'),false);
});
test('unsupported notifications do not prevent focus',()=>{
  let focused=false;
  const win={isDestroyed:()=>false,isMinimized:()=>false,isVisible:()=>true,focus:()=>{focused=true}};
  assert.equal(requestApprovalAttention(win,{isSupported:()=>false},'MCPtoAI'),true);
  assert.equal(focused,true);
});
