// GitHub MCP kurulum testleri (ağ gerektirir: sabitlenmiş sürümü gerçekten indirir).
// Çalıştırma: node src/github-mcp.install.test.js
const assert=require('assert'),fs=require('fs'),os=require('os'),path=require('path');
const {installOfficial,MARKER}=require('./github-mcp');
const realFetch=global.fetch;let downloads=0;
global.fetch=(...a)=>{downloads++;return realFetch(...a)};
(async()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'mcptoai-gh-test-'));
  try{
    // 1) İlk kurulum: indirir, işaret dosyasını yazar
    let r=await installOfficial(root);
    assert.equal(r.reused,false);assert.equal(downloads,1);
    const dir=path.dirname(r.binary);assert.ok(fs.existsSync(path.join(dir,MARKER)),'işaret dosyası yok');
    console.log('ok 1 - ilk kurulum indirir ve işaret yazar');
    // 2) Doğrulanmış kurulum: indirme YOK
    r=await installOfficial(root);
    assert.equal(r.reused,true);assert.equal(downloads,1);
    console.log('ok 2 - doğrulanmış kurulum indirmeden yeniden kullanılır');
    // 3) Bozulmuş ikili dosya (yarım yazılmış gibi): yeniden indirilip onarılır
    fs.truncateSync(r.binary,1024);
    r=await installOfficial(root);
    assert.equal(r.reused,false);assert.equal(downloads,2);assert.ok(fs.statSync(r.binary).size>1e6);
    console.log('ok 3 - bozuk ikili dosya fark edilir ve onarılır');
    // 4) İşaretsiz klasör (kesilmiş kurulum): yeniden kullanılmaz
    fs.unlinkSync(path.join(path.dirname(r.binary),MARKER));
    r=await installOfficial(root);
    assert.equal(r.reused,false);assert.equal(downloads,3);
    console.log('ok 4 - işaretsiz (yarım) kurulum yeniden kullanılmaz');
    // 5) Çalışan ikili dosya varken yeniden kurulum: dosyaya dokunulmaz.
    // Sürecin gerçekten çalıştığı doğrulanır; aksi halde (Windows'ta) dosya kilidi hiç sınanmamış olur.
    const {spawn}=require('child_process');
    const startServer=bin=>{const p=spawn(bin,['stdio'],{stdio:['pipe','ignore','ignore'],env:{...process.env}});return new Promise(x=>setTimeout(()=>x(p),1200))};
    let p=await startServer(r.binary);assert.equal(p.exitCode,null,'test sunucusu başlamadı; kilit sınanamaz');
    const ino=fs.statSync(r.binary).ino;
    r=await installOfficial(root);
    assert.equal(p.exitCode,null);assert.equal(r.reused,true);assert.equal(fs.statSync(r.binary).ino,ino);assert.equal(downloads,3);
    console.log('ok 5 - çalışan sunucu varken aynı dosya korunur');
    // 6) Yarım kurulum (işaret yok) + çalışan sunucu: Windows'ta klasör silinemez.
    // Çökme yerine anlaşılır hata verilmeli ve çalışan dosya bozulmamalı.
    fs.unlinkSync(path.join(path.dirname(r.binary),MARKER));
    if(process.platform==='win32'){
      await assert.rejects(installOfficial(root),/could not be replaced.*Restart MCPtoAI/);
      assert.ok(fs.existsSync(r.binary));assert.equal(p.exitCode,null);
      console.log('ok 6 - kilitli yarım kurulumda anlaşılır hata, çalışan dosya korunur');
    }else{
      r=await installOfficial(root);assert.equal(r.reused,false);
      console.log('ok 6 - (macOS) yarım kurulum çalışan sunucuya rağmen yenilenir');
    }
    p.kill();await new Promise(x=>setTimeout(x,500));
    console.log('github-mcp install: 6/6 OK');
  }finally{fs.rmSync(root,{recursive:true,force:true});global.fetch=realFetch}
})().catch(e=>{console.error('BAŞARISIZ:',e.message);process.exit(1)});
