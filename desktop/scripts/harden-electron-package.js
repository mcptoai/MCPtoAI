const fs = require('fs');
const os = require('os');
const path = require('path');
const asar = require('@electron/asar');
const terser = require('terser');

const UNSAFE_PACKAGED_FILE_RE = /(?:\.bak(?:[_\d.-]|$)|\.old(?:$|[._-])|\.orig(?:$|[._-])|\.tmp(?:$|[._-])|~$)/i;

async function walk(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...await walk(p));
    else if (ent.isFile()) out.push(p);
  }
  return out;
}

module.exports = async function hardenElectronPackage(context) {
  const platform = context.electronPlatformName;
  const appOutDir = context.appOutDir;
  const productName = context.packager.appInfo.productName;
  const resources = platform === 'darwin'
    ? path.join(appOutDir, `${productName}.app`, 'Contents', 'Resources')
    : path.join(appOutDir, 'resources');
  const appAsar = path.join(resources, 'app.asar');
  if (!fs.existsSync(appAsar)) throw new Error(`app.asar missing: ${appAsar}`);

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'mcptoai-asar-'));
  const extracted = path.join(tmp, 'app');
  const rebuilt = path.join(tmp, 'app.asar');
  try {
    asar.extractAll(appAsar, extracted);
    const icon = path.join(extracted, 'build', 'icon.png');
    if (!fs.existsSync(icon) || fs.statSync(icon).size === 0) throw new Error('Missing build/icon.png inside app.asar');
    const src = path.join(extracted, 'src');
    let minified = 0;
    if (fs.existsSync(src)) {
      for (const file of await walk(src)) {
        if (!file.endsWith('.js')) continue;
        const code = fs.readFileSync(file, 'utf8');
        const result = await terser.minify(code, {
          compress: false,
          mangle: false,
          ecma: 2020,
          format: { comments: false, beautify: false },
        });
        if (!result.code) throw new Error(`Terser returned empty output for ${file}`);
        fs.writeFileSync(file, `${result.code}\n`);
        minified += 1;
      }
    }

    let mapsRemoved = 0;
    for (const file of await walk(extracted)) {
      if (file.endsWith('.map')) {
        fs.rmSync(file);
        mapsRemoved += 1;
      }
    }

    const excluded = [];
    for (const file of await walk(extracted)) {
      if (UNSAFE_PACKAGED_FILE_RE.test(path.basename(file))) {
        fs.rmSync(file);
        excluded.push(path.relative(extracted, file));
      }
    }

    await asar.createPackage(extracted, rebuilt);
    fs.copyFileSync(rebuilt, appAsar);
    console.log(`MCPtoAI package hardening: minified ${minified} JS files, removed ${mapsRemoved} source maps, excluded ${excluded.length} backup/temp files`);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
};
