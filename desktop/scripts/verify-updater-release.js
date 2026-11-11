'use strict';
const path=require('path'),{verify}=require('./verify-updater-artifacts');
const platform=process.argv[2];
if(platform!=='win'&&platform!=='mac')throw new Error('Expected win or mac');
const version=require('../package.json').version;
verify(path.resolve(__dirname,'../dist'),platform==='win'?'latest.yml':'latest-mac.yml',version,platform==='win'?'.exe':'.zip');
console.log(`Updater manifest, payload SHA-512, size and blockmap present: ${platform} ${version}`);
