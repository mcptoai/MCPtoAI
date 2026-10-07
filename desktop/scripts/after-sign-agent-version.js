'use strict';
// electron-builder afterSign kancası.
// İmzalama, pakete giren Device Agent'ın ikili dosyalarını (dylib vb.) yeniden imzalayıp
// baytlarını değiştirir. agent-version.json ise imzalamadan ÖNCE yazıldığı için içindeki
// özet artık tutmaz ve uygulama agent kurulumunu "integrity check failed" ile reddeder.
// Bu kanca özeti imzalı ağaçtan yeniden hesaplar ve yalnızca dış .app paketini yeniden
// mühürler; içteki imzalı dosyalara dokunulmaz, böylece özet sabit kalır.
// NOT: Notarization etkinleştirilirse bu kancanın notarization'dan ÖNCE çalıştığı
// doğrulanmalıdır; aksi halde yeniden mühürleme notarization'ı geçersiz kılar.
const fs=require('fs'),path=require('path'),crypto=require('crypto'),{execFileSync}=require('child_process');

// src/agent-install.js içindeki hashTree ile birebir aynı algoritma (değiştirilirse ikisi birlikte).
function hashTree(dir){const h=crypto.createHash('sha256');const walk=d=>fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(path.join(d,e.name)):e.isFile()?[path.join(d,e.name)]:[]).sort();for(const f of walk(dir)){h.update(path.relative(dir,f));h.update('\0');h.update(fs.readFileSync(f));h.update('\0')}return h.digest('hex')}

exports.hashTree=hashTree;
exports.default=async function afterSign(context){
  if(context.electronPlatformName!=='darwin')return;
  const app=path.join(context.appOutDir,`${context.packager.appInfo.productFilename}.app`);
  const res=path.join(app,'Contents','Resources'),verFile=path.join(res,'agent-version.json');
  const meta=JSON.parse(fs.readFileSync(verFile,'utf8')),actual=hashTree(path.join(res,'agent'));
  if(meta.sha256===actual){console.log('  • agent-version.json zaten imzalı ağaçla eşleşiyor');return}
  fs.writeFileSync(verFile,JSON.stringify({...meta,sha256:actual},null,2)+'\n');
  const opts=context.packager.platformSpecificBuildOptions||{};
  if(!opts.identity){console.log('  • imzasız derleme: agent-version.json güncellendi, yeniden mühürleme yok');return}
  const args=['--force','--sign',opts.identity,'--timestamp'];
  if(opts.hardenedRuntime!==false)args.push('--options','runtime');
  if(opts.entitlements)args.push('--entitlements',path.resolve(context.packager.projectDir,opts.entitlements));
  execFileSync('/usr/bin/codesign',[...args,app],{stdio:'inherit'});
  execFileSync('/usr/bin/codesign',['--verify','--deep','--strict',app],{stdio:'inherit'});
  console.log(`  • agent-version.json imzalı ağaca göre güncellendi (${actual.slice(0,12)}…) ve paket yeniden mühürlendi`);
};
