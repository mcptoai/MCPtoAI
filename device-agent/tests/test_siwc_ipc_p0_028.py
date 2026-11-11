from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def test_siwc_ipc_validates_main_frame_and_local_app_url():
    js=(ROOT/'desktop/src/main.js').read_text()
    assert 'function trustedSiwcSender(event)' in js
    assert 'frame!==sender.mainFrame' in js
    assert 'w.webContents===sender' in js
    assert "url.protocol==='file:'" in js
    assert "fileURLToPath(url)" in js
    assert "ipcMain.handle('siwc:preview',(event,action)=>{if(!trustedSiwcSender(event))" in js
    assert "if(!trustedSiwcSender(event))return resolve({ok:false,error:'Untrusted SIWC caller'})" in js
    assert "ipcMain.handle('siwc:usage-link',(event)=>trustedSiwcSender(event)" in js
