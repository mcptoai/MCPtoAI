const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const installer=fs.readFileSync(path.join(__dirname,'agent-install-windows.js'),'utf8');
const platform=fs.readFileSync(path.join(__dirname,'platform.js'),'utf8');
test('Windows upgrade requires scheduled task and removes legacy Run only after registration',()=>{
 assert.match(installer,/Register-ScheduledTask/);
 assert.match(installer,/Start-ScheduledTask -TaskName \$name/);
 assert.match(installer,/execFileSync\('reg\.exe',\['DELETE',RUN_KEY/);
 assert.doesNotMatch(installer,/falling back to Run|function autostart\(/);
 assert.match(installer,/Legacy Run value still exists after removal/);
});
test('Windows bundle validates both executables and stop targets both',()=>{
 assert.match(installer,/Bundled Windows background agent is missing/);
 assert.match(installer,/health\(backgroundExe\(p\.exe\)\)/);
 assert.match(installer,/Supervisor\/agent processes did not exit/);
 assert.match(platform,/WIN_BACKGROUND_EXE/);
 assert.match(platform,/Device Agent installation incomplete/);
});
test('Windows Start and Stop use Task Scheduler, never independent supervisor spawn',()=>{
 assert.match(platform,/Enable-ScheduledTask -TaskName 'MCPtoAI Agent'/);
 assert.match(platform,/Disable-ScheduledTask -TaskName 'MCPtoAI Agent'/);
 assert.match(platform,/Stop-ScheduledTask -TaskName 'MCPtoAI Agent'/);
 assert.doesNotMatch(platform,/Start-Process -FilePath/);
});
