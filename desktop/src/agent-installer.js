const mac=require('./agent-install');
const win=require('./agent-install-windows');
function impl(){return process.platform==='win32'?win:mac}
module.exports={install:r=>impl().install(r),status:r=>impl().status(r),upgradeIfNeeded:r=>{const i=impl();return typeof i.upgradeIfNeeded==='function'?i.upgradeIfNeeded(r):{ok:true,updated:false,...i.status(r)}}};
