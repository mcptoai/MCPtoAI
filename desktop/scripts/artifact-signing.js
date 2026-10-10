const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

exports.default = async function artifactSign(configuration) {
  const file = configuration && configuration.path;
  if (!file || !fs.existsSync(file)) throw new Error(`Artifact Signing target missing: ${file || '<empty>'}`);

  const signTool = 'C:\\Program Files (x86)\\Windows Kits\\10\\bin\\10.0.26100.0\\x64\\signtool.exe';
  const dlib = path.join(os.homedir(), 'AppData', 'Local', 'Microsoft', 'MicrosoftArtifactSigningClientTools', 'Azure.CodeSigning.Dlib.dll');
  const metadata = path.join(__dirname, '..', 'build', 'artifact-signing-metadata.json');
  for (const required of [signTool, dlib, metadata]) {
    if (!fs.existsSync(required)) throw new Error(`Artifact Signing dependency missing: ${required}`);
  }

  const env = { ...process.env };
  const azCli = 'C:\\Program Files\\Microsoft SDKs\\Azure\\CLI2\\wbin';
  env.PATH = `${azCli};${env.PATH || ''}`;
  // Preserve an existing valid BKTY LTD signature. This keeps the bundled
  // Device Agent bytes stable after agent-version.json has been generated.
  const existingVerify = spawnSync(signTool, ['verify', '/pa', file], { env, encoding: 'utf8', timeout: 30000 });
  if (existingVerify.status === 0) {
    const escaped = file.replace(/'/g, "''");
    const ps = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', `(Get-AuthenticodeSignature -LiteralPath '${escaped}').SignerCertificate.Subject`], { encoding: 'utf8', timeout: 15000 });
    if (ps.status === 0 && /CN=BKTY LTD(?:,|$)/i.test(String(ps.stdout || ''))) return;
  }

  const args = [
    'sign', '/v', '/fd', 'SHA256',
    '/tr', 'http://timestamp.acs.microsoft.com', '/td', 'SHA256',
    '/dlib', dlib, '/dmdf', metadata, file,
  ];
  const signed = spawnSync(signTool, args, { env, encoding: 'utf8', timeout: 120000 });
  if (signed.status !== 0) throw new Error(`Artifact Signing failed for ${file}\n${signed.stdout || ''}\n${signed.stderr || ''}`);

  const verify = spawnSync(signTool, ['verify', '/pa', file], { env, encoding: 'utf8', timeout: 30000 });
  if (verify.status !== 0) throw new Error(`Artifact Signing verification failed for ${file}\n${verify.stdout || ''}\n${verify.stderr || ''}`);
};
