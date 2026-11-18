const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'main.js'),'utf8');
test('native approval uses Electron main dialog and does not reach renderer',()=>{
  assert.match(source,/if\(msg\.native_action===true\)\{void showNativeActionApproval\(msg\);continue\}/);
  assert.match(source,/dialog\.showMessageBox\(win,/);
  assert.match(source,/if\(item\.native\)return \{ok:false,error:'Native approval cannot be supplied by the renderer\.'\}/);
  assert.match(source,/pendingChatApprovals\.delete\(aid\)/);
});
