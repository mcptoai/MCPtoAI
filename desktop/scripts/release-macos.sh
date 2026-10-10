#!/bin/zsh
set -euo pipefail
cd "${0:A:h:h}"
IDENTITY="${MCPTOAI_DEVELOPER_ID:-}"
PROFILE="${MCPTOAI_NOTARY_PROFILE:-}"
if [[ -z "$IDENTITY" || -z "$PROFILE" ]]; then
  print -u2 'Set MCPTOAI_DEVELOPER_ID and MCPTOAI_NOTARY_PROFILE before distribution.'; exit 2
fi
security find-identity -v -p codesigning | grep -Fq "\"$IDENTITY\"" || { print -u2 'Developer ID identity unavailable.'; exit 2; }
DESKTOP_VERSION=$(node -p "require('./package.json').version")
AGENT_VERSION=$(../device-agent/.venv/bin/python -c "import tomllib; print(tomllib.load(open('../device-agent/pyproject.toml','rb'))['project']['version'])")
[[ "$DESKTOP_VERSION" == "$AGENT_VERSION" ]] || { print -u2 "Version mismatch: Desktop $DESKTOP_VERSION != Agent $AGENT_VERSION"; exit 2; }
# Build native permission helper and Python agent.
npm run build:permission-helper:mac
npm run build:agent:mac
# Sign the bundled Python executable before electron-builder signs the outer app.
AGENT="../device-agent/dist/mcptoai-agent/mcptoai-agent"
codesign --force --sign "$IDENTITY" --options runtime --timestamp "$AGENT"
codesign --verify --strict --verbose=2 "$AGENT"
HELPER="native/bin/permission-helper"
codesign --force --sign "$IDENTITY" --options runtime --timestamp "$HELPER"
codesign --verify --strict --verbose=2 "$HELPER"
# codesign changes executable bytes; regenerate the bundled integrity metadata afterwards.
node scripts/write-agent-version.js
# Build a real signed macOS app bundle for the background Device Agent.
# The LaunchAgent points to this bundle's native main executable, so macOS can
# attribute Background Activity to MCPtoAI instead of the certificate owner.
node scripts/build-device-agent-bundle-mac.js
AGENT_APP="build/device-agent/MCPtoAI Device Agent.app"
AGENT_LAUNCHER="$AGENT_APP/Contents/MacOS/mcptoai-device-agent"
codesign --force --sign "$IDENTITY" --options runtime --timestamp "$AGENT_LAUNCHER"
codesign --force --sign "$IDENTITY" --options runtime --timestamp "$AGENT_APP"
codesign --verify --deep --strict --verbose=2 "$AGENT_APP"
BUILDER_IDENTITY="${IDENTITY#Developer ID Application: }"
export CSC_NAME="$BUILDER_IDENTITY"
npx electron-builder --mac dir --config.mac.identity="$BUILDER_IDENTITY" --config.mac.hardenedRuntime=true
DMG="dist/MCPtoAI-$(node -p "require('./package.json').version")-arm64.dmg"
APP="dist/mac-arm64/MCPtoAI.app"
[[ -d "$APP" ]] || { print -u2 "Expected packaged app not found: $APP"; exit 3; }
BUNDLED_AGENT_APP="$APP/Contents/Library/LoginItems/MCPtoAI Device Agent.app"
BUNDLED_AGENT="$BUNDLED_AGENT_APP/Contents/Resources/agent/mcptoai-agent"
BUNDLED_HELPER="$BUNDLED_AGENT_APP/Contents/Resources/permission-helper"
# electron-builder has now produced the final signed app. Compute the integrity
# hash from that final tree, then write the metadata and re-sign ONLY the outer
# app with its required entitlements. This preserves all nested Electron seals.
node - "$BUNDLED_AGENT_APP/Contents/Resources/agent" "$APP/Contents/Resources/agent-version.json" <<'NODE'
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const [dir,out]=process.argv.slice(2);
function files(d){return fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(path.join(d,e.name)):e.isFile()?[path.join(d,e.name)]:[]).sort()}
const h=crypto.createHash('sha256'); for(const f of files(dir)){h.update(path.relative(dir,f));h.update('\0');h.update(fs.readFileSync(f));h.update('\0')}
const meta=JSON.parse(fs.readFileSync(out,'utf8')); meta.sha256=h.digest('hex'); fs.writeFileSync(out,JSON.stringify(meta,null,2)+'\n');
NODE
codesign --force --sign "$IDENTITY" --options runtime --timestamp --entitlements "build/entitlements.mac.plist" "$APP"
for TARGET in "$APP" "$APP/Contents/Frameworks/MCPtoAI Helper (Renderer).app"; do
  codesign -d --entitlements - "$TARGET" 2>/dev/null | grep -q 'com.apple.security.cs.allow-jit' || { print -u2 "Missing allow-jit entitlement: $TARGET"; exit 3; }
done
codesign --verify --strict --verbose=2 "$BUNDLED_AGENT"
codesign --verify --strict --verbose=2 "$BUNDLED_HELPER"
codesign --verify --deep --strict --verbose=2 "$BUNDLED_AGENT_APP"
codesign -dv --verbose=2 "$BUNDLED_AGENT" 2>&1 | grep -F "TeamIdentifier=WCUHC7RX92"
codesign --verify --deep --strict --verbose=2 "$APP"
# Build the DMG only after final metadata and final app signature are complete.
npx electron-builder --mac dmg --prepackaged "$APP" --config.mac.identity="$BUILDER_IDENTITY" --config.mac.hardenedRuntime=true
# Sign the DMG itself so Gatekeeper can assess the distribution container.
codesign --force --sign "$IDENTITY" --timestamp "$DMG"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
spctl --assess --type execute --verbose=4 "$APP"
spctl --assess --type open --context context:primary-signature --verbose=4 "$DMG"
shasum -a 256 "$DMG"
