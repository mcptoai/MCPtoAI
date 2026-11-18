'use strict';

function requestApprovalAttention(win,Notification,title){
  // Onay öncesinde pencereyi görünür ve odaklı yap; bildirim yalnızca uyarıdır.
  if(!win||win.isDestroyed())return false;
  try{
    if(win.isMinimized())win.restore();
    if(!win.isVisible())win.show();
    win.focus();
    if(Notification?.isSupported?.()){
      new Notification({title,body:'An incoming request needs your approval on this device.'}).show();
    }
    return true;
  }catch{return false}
}
module.exports={requestApprovalAttention};
