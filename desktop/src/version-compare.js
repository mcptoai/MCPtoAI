function compareVersions(a,b){
  const parse=v=>{const m=String(v||'').trim().replace(/^v/i,'').match(/^(\d+)\.(\d+)\.(\d+)/);return m?[Number(m[1]),Number(m[2]),Number(m[3])]:null};
  const x=parse(a),y=parse(b);if(!x||!y)return 0;for(let i=0;i<3;i++){if(x[i]>y[i])return 1;if(x[i]<y[i])return -1}return 0;
}
module.exports={compareVersions};
