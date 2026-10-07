const assert=require('assert');const {compareVersions}=require('./version-compare');
assert.equal(compareVersions('0.1.7','0.1.5'),1);
assert.equal(compareVersions('0.1.5','0.1.7'),-1);
assert.equal(compareVersions('0.1.7','0.1.7'),0);
assert.equal(compareVersions('1.0.0','0.99.99'),1);
console.log('version-compare: 4/4 OK');
