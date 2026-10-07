const fs=require('fs'),path=require('path'),crypto=require('crypto');
const root=path.resolve(__dirname,'../..'),agent=path.join(root,'device-agent'),out=path.join(__dirname,'..','agent-version.json');
const toml=fs.readFileSync(path.join(agent,'pyproject.toml'),'utf8');const m=toml.match(/^version\s*=\s*"([^"]+)"/m);if(!m)throw new Error('Agent version missing');
const dist=path.join(agent,'dist','mcptoai-agent');
function files(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(path.join(dir,e.name)):e.isFile()?[path.join(dir,e.name)]:[]).sort()}
const h=crypto.createHash('sha256');for(const f of files(dist)){h.update(path.relative(dist,f));h.update('\0');h.update(fs.readFileSync(f));h.update('\0')}
fs.writeFileSync(out,JSON.stringify({version:m[1],sha256:h.digest('hex')},null,2)+'\n');console.log(`Agent ${m[1]} metadata written`);
