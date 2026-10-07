const assert=require('assert');
const {assetName}=require('./github-mcp');
assert.equal(assetName('darwin','arm64'),'github-mcp-server_Darwin_arm64.tar.gz');
assert.equal(assetName('darwin','x64'),'github-mcp-server_Darwin_x86_64.tar.gz');
assert.equal(assetName('win32','x64'),'github-mcp-server_Windows_x86_64.zip');
assert.equal(assetName('win32','arm64'),'github-mcp-server_Windows_arm64.zip');
console.log('github-mcp selector OK');
