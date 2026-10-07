const fs=require('fs'),path=require('path'),crypto=require('crypto');
const root=path.resolve(__dirname,'../..');
const agent=path.join(root,'device-agent');
const out=path.join(__dirname,'..','agent-version.json');
const toml=fs.readFileSync(path.join(agent,'pyproject.toml'),'utf8');
const m=toml.match(/^version\s*=\s*"([^"]+)"/m);
if(!m)throw new Error('Agent version missing');
const dist=path.join(agent,'dist','mcptoai-agent');
function files(d){return fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(path.join(d,e.name)):e.isFile()?[path.join(d,e.name)]:[]).sort()}
function fileHash(f){return crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex')}
function hashTree(dir){const entries=files(dir).map(f=>`${path.relative(dir,f).split(path.sep).join('/')}\0${fileHash(f)}\0`).join('');return crypto.createHash('sha256').update(entries,'utf8').digest('hex')}
fs.writeFileSync(out,JSON.stringify({version:m[1],sha256:hashTree(dist)},null,2)+'\n');
