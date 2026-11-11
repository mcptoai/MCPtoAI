const mac=require('./agent-install');
const win=require('./agent-install-windows');
function impl(){return process.platform==='win32'?win:mac}
module.exports={install:r=>impl().install(r),status:r=>impl().status(r),upgradeIfNeeded:(r,log)=>{const i=impl();return typeof i.upgradeIfNeeded==='function'?i.upgradeIfNeeded(r,log):{ok:true,updated:false,...i.status(r)}}};
