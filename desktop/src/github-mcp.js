const fs=require('fs');
const path=require('path');
const os=require('os');
const crypto=require('crypto');
const {spawnSync}=require('child_process');

const OWNER='github';
const REPO='github-mcp-server';
const VERSION='1.12.2';
const BASE=`https://github.com/${OWNER}/${REPO}/releases/download/v${VERSION}`;
const DIGESTS={
  'github-mcp-server_Darwin_arm64.tar.gz':'7e6c5aec43f26b82d3580e77a4ee26872bcd34b48c9a08d0eaef48b5d0563904',
  'github-mcp-server_Darwin_x86_64.tar.gz':'6e73f5c9738050e44318d37aa919cb8ed2e29453d6341e942dc9c40c9c7ced5b',
  'github-mcp-server_Windows_x86_64.zip':'c08872e69f700d4219e7b4ab9607d56d7993171519ee32b62fccb8fba0cab673',
  'github-mcp-server_Windows_arm64.zip':'3290d0f26b0aa75f3c8d88ea4e07f0101f7e1555170dc7affa9454acf6636b4c',
};

function assetName(platform=process.platform,arch=process.arch){
  if(platform==='darwin'&&arch==='arm64') return 'github-mcp-server_Darwin_arm64.tar.gz';
  if(platform==='darwin'&&arch==='x64') return 'github-mcp-server_Darwin_x86_64.tar.gz';
  if(platform==='win32'&&arch==='x64') return 'github-mcp-server_Windows_x86_64.zip';
  if(platform==='win32'&&arch==='arm64') return 'github-mcp-server_Windows_arm64.zip';
  throw new Error(`GitHub MCP is not available for ${platform}/${arch}.`);
}
function sha256(buf){return crypto.createHash('sha256').update(buf).digest('hex')}
function findBinary(dir,platform=process.platform){
  const want=platform==='win32'?'github-mcp-server.exe':'github-mcp-server';
  const stack=[dir];
  while(stack.length){const d=stack.pop();for(const e of fs.readdirSync(d,{withFileTypes:true})){const p=path.join(d,e.name);if(e.isDirectory())stack.push(p);else if(e.isFile()&&e.name===want)return p}}
  return '';
}
function pruneOldVersions(base,keep){
  try{for(const e of fs.readdirSync(base,{withFileTypes:true})){if(e.isDirectory()&&e.name!==keep)fs.rmSync(path.join(base,e.name),{recursive:true,force:true})}}catch{}
}
// Kurulumun tamamlandığını gösteren işaret dosyası. Yalnızca arşiv doğrulanıp
// açıldıktan sonra yazılır; yarım kalmış bir kurulum asla yeniden kullanılmaz.
const MARKER='.install-ok.json';
function fileSha256(p){return sha256(fs.readFileSync(p))}
function verifiedExisting(root,platform,expected){
  try{
    const m=JSON.parse(fs.readFileSync(path.join(root,MARKER),'utf8'));
    if(m.archive_sha256!==expected)return '';
    const bin=findBinary(root,platform);
    if(!bin||fileSha256(bin)!==m.binary_sha256)return '';
    return bin;
  }catch{return ''}
}
async function installOfficial(configRoot,{platform=process.platform,arch=process.arch}={}){
  const name=assetName(platform,arch),expected=DIGESTS[name];
  if(!expected)throw new Error(`Pinned GitHub MCP digest missing: ${name}`);
  const base=path.join(configRoot,'integrations','github'),root=path.join(base,VERSION);
  // Doğrulanmış kurulum varsa indirmeden yeniden kullan. Windows'ta çalışan .exe
  // silinemediği için aynı sürüm klasörüne asla yeniden yazılmaz.
  const existing=verifiedExisting(root,platform,expected);
  if(existing){if(platform!=='win32')fs.chmodSync(existing,0o700);return {version:VERSION,binary:existing,sha256:expected,asset:name,reused:true}}
  const dl=await fetch(`${BASE}/${name}`,{redirect:'follow',headers:{'User-Agent':'MCPtoAI'}});
  if(!dl.ok)throw new Error(`GitHub MCP download failed (HTTP ${dl.status}).`);
  const buf=Buffer.from(await dl.arrayBuffer()),actual=sha256(buf);
  if(actual.toLowerCase()!==expected.toLowerCase())throw new Error('GitHub MCP download failed pinned SHA-256 verification.');
  // İşaretsiz (yarım kalmış) eski klasör temizlenir; kilitliyse anlaşılır hata ver.
  if(fs.existsSync(root)){
    try{fs.rmSync(root,{recursive:true,force:true})}
    catch(e){throw new Error(`Previous GitHub MCP install is incomplete and could not be replaced (${e.code||e.message}). Restart MCPtoAI and try again.`)}
  }
  fs.mkdirSync(root,{recursive:true});
  const tmp=path.join(os.tmpdir(),`mcptoai-github-mcp-${process.pid}-${Date.now()}${platform==='win32'?'.zip':'.tar.gz'}`);
  fs.writeFileSync(tmp,buf,{mode:0o600});
  try{
    let r;
    if(platform==='win32')r=spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-Command','& { param($archive,$dest) Expand-Archive -LiteralPath $archive -DestinationPath $dest -Force }',tmp,root],{encoding:'utf8',timeout:60000});
    else r=spawnSync('/usr/bin/tar',['-xzf',tmp,'-C',root],{encoding:'utf8',timeout:60000});
    if(r.status!==0)throw new Error((r.stderr||r.stdout||'Could not extract GitHub MCP').trim());
  }finally{try{fs.unlinkSync(tmp)}catch{}}
  const binary=findBinary(root,platform);if(!binary)throw new Error('GitHub MCP binary was not found after extraction.');
  if(platform!=='win32')fs.chmodSync(binary,0o700);
  fs.writeFileSync(path.join(root,MARKER),JSON.stringify({version:VERSION,archive_sha256:expected,binary_sha256:fileSha256(binary)}),{mode:0o600});
  return {version:VERSION,binary,sha256:actual,asset:name,reused:false};
}
module.exports={installOfficial,assetName,VERSION,DIGESTS,MARKER};
