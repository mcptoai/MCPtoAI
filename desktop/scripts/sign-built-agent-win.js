const path = require('path');
const { default: sign } = require('./artifact-signing');
(async () => {
  const file = path.resolve(__dirname, '../../device-agent/dist/mcptoai-agent/mcptoai-agent.exe');
  await sign({ path: file });
  await sign({ path: path.join(path.dirname(file), 'mcptoai-agent-background.exe') });
})().catch((err) => { console.error(err && err.stack ? err.stack : String(err)); process.exit(1); });
