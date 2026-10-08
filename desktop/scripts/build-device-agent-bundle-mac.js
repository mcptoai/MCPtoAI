'use strict';
const fs=require('fs'),path=require('path'),{execFileSync}=require('child_process');
const desktop=path.resolve(__dirname,'..');
const root=path.resolve(desktop,'..');
const agentSource=path.join(root,'device-agent','dist','mcptoai-agent');
const helperSource=path.join(desktop,'native','bin','permission-helper');
const launcherSource=path.join(desktop,'native','AgentLauncher.c');
const outRoot=path.join(desktop,'build','device-agent');
const app=path.join(outRoot,'MCPtoAI Device Agent.app');
const contents=path.join(app,'Contents'),macos=path.join(contents,'MacOS'),resources=path.join(contents,'Resources');
const launcher=path.join(macos,'mcptoai-device-agent');
const agentDir=path.join(resources,'agent');
const helper=path.join(resources,'permission-helper');
const pkg=require(path.join(desktop,'package.json'));
const version=pkg.version;
if(!fs.existsSync(path.join(agentSource,'mcptoai-agent')))throw new Error('Built macOS Device Agent is missing.');
if(!fs.existsSync(helperSource))throw new Error('Built permission helper is missing.');
fs.rmSync(outRoot,{recursive:true,force:true});
fs.mkdirSync(macos,{recursive:true});fs.mkdirSync(resources,{recursive:true});
fs.cpSync(agentSource,agentDir,{recursive:true,verbatimSymlinks:true});
fs.copyFileSync(helperSource,helper);fs.chmodSync(helper,0o755);
execFileSync('/usr/bin/xcrun',['clang','-O2',launcherSource,'-o',launcher],{stdio:'inherit'});
fs.chmodSync(launcher,0o755);
const info={
  CFBundleDevelopmentRegion:'en',
  CFBundleDisplayName:'MCPtoAI Device Agent',
  CFBundleExecutable:'mcptoai-device-agent',
  CFBundleIdentifier:'com.bkty.mcptoai.device-agent',
  CFBundleInfoDictionaryVersion:'6.0',
  CFBundleName:'MCPtoAI Device Agent',
  CFBundlePackageType:'APPL',
  CFBundleShortVersionString:version,
  CFBundleVersion:String(version).replace(/[^0-9]/g,'')||'1',
  LSBackgroundOnly:true,
  NSMicrophoneUsageDescription:'MCPtoAI uses microphone access only when you allow a microphone tool.',
  NSCameraUsageDescription:'MCPtoAI uses camera access only when you allow a camera tool.'
};
execFileSync('/usr/bin/plutil',['-convert','xml1','-o',path.join(contents,'Info.plist'),'--','-'],{input:JSON.stringify(info)});
console.log(`Built ${app}`);
