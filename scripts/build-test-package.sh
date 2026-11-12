#!/usr/bin/env bash
# MCPtoAI — macOS test paketi derleme betiği.
#
# Kullanım:
#   scripts/build-test-package.sh <commit-sha|tag> [--notarize] [--remote <git-url>]
#
# Ne yapar:
#   1. Tek bir kalıcı klonu günceller ve kalıcı bir derleme worktree'sini istenen commit'e geçirir.
#   2. Lock dosyalarının hash'i değişmediyse .venv ve node_modules'ü yeniden kurmaz.
#   3. release-macos.sh'ı MCPTOAI_RELEASE_BUILD=1 ile çalıştırır (notarization varsayılan KAPALI).
#   4. Paketi doğrular ve özeti artifacts/<commit>-<zaman>/SUMMARY.txt dosyasına yazar.
#
# İmzalama ayarları (sır değildir) ~/.config/mcptoai/build.env dosyasından okunur:
#   MCPTOAI_DEVELOPER_ID="Developer ID Application: ... (TEAMID)"
#   MCPTOAI_NOTARY_PROFILE="uhm-notary"
#
# Herhangi bir adım başarısız olursa betik durur.

set -Eeuo pipefail
# Beklenmedik bir komut betiği durdurursa satır ve çıkış kodu yazılır (sessiz çıkış olmasın).
trap 'rc=$?; echo "HATA: satır $LINENO beklenmedik şekilde durdu (çıkış $rc): $BASH_COMMAND" >&2' ERR

# --- Argümanlar ---------------------------------------------------------------
COMMIT=""
NOTARIZE=0
REMOTE="${MCPTOAI_CORE_REMOTE:-git@github.com:mcptoai/MCPtoAI_Core.git}"

while [ $# -gt 0 ]; do
  case "$1" in
    --notarize) NOTARIZE=1 ;;
    --remote) shift; REMOTE="$1" ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    -*) echo "Bilinmeyen seçenek: $1" >&2; exit 2 ;;
    *) COMMIT="$1" ;;
  esac
  shift
done

if [ -z "$COMMIT" ]; then
  echo "Kullanım: $0 <commit-sha|tag> [--notarize] [--remote <git-url>]" >&2
  exit 2
fi

# --- Ayarlar ------------------------------------------------------------------
ROOT="${MCPTOAI_BUILD_ROOT:-$HOME/MCPtoAI-private-builds}"
REPO="$ROOT/core-main"          # Tek kalıcı klon
WT="$ROOT/build-wt"             # Kalıcı derleme worktree'si (yol sabit kalır)
CONFIG="$HOME/.config/mcptoai/build.env"

mkdir -p "$ROOT/artifacts" "$ROOT/logs"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$ROOT/logs/build-$STAMP.log"
exec > >(tee -a "$LOG") 2>&1

step() { printf '\n=== %s ===\n' "$*"; }
fail() { echo "HATA: $*" >&2; exit 1; }

if [ -f "$CONFIG" ]; then
  # shellcheck disable=SC1090
  . "$CONFIG"
fi
: "${MCPTOAI_DEVELOPER_ID:?build.env içinde MCPTOAI_DEVELOPER_ID tanımlı değil ($CONFIG)}"
if [ "$NOTARIZE" = 1 ]; then
  : "${MCPTOAI_NOTARY_PROFILE:?--notarize için build.env içinde MCPTOAI_NOTARY_PROFILE gerekli}"
fi

command -v python3.14 >/dev/null || fail "python3.14 bulunamadı"
command -v npm >/dev/null || fail "npm bulunamadı"

# --- 1. Kaynak ----------------------------------------------------------------
step "Kaynak: $COMMIT"
if [ ! -d "$REPO/.git" ]; then
  git clone "$REMOTE" "$REPO"
fi
git -C "$REPO" fetch --tags --prune origin
SHA="$(git -C "$REPO" rev-parse --verify "${COMMIT}^{commit}")" || fail "commit bulunamadı: $COMMIT"
SHORT="${SHA:0:7}"
echo "Commit: $SHA"

if [ ! -e "$WT/.git" ]; then
  git -C "$REPO" worktree add --detach "$WT" "$SHA"
else
  # Kalıcı worktree: önceki derlemenin çıktılarını temizle, ortamları koru.
  git -C "$WT" checkout --detach --force "$SHA"
  git -C "$WT" clean -xfd -e device-agent/.venv -e desktop/node_modules
fi

[ "$(git -C "$WT" rev-parse HEAD)" = "$SHA" ] || fail "worktree beklenen commit'te değil"
if [ -n "$(git -C "$WT" status --porcelain)" ]; then
  git -C "$WT" status --porcelain
  fail "çalışma ağacı temiz değil"
fi

# --- 2. Python ortamı ----------------------------------------------------------
# setup-build-env.py (build:agent:mac içinden) mevcut .venv'i yeniden kullanır.
# Lock dosyası değiştiyse eski paketler kalmasın diye .venv silinir ve temiz kurulur.
step "Python derleme ortamı"
PY_LOCK="$WT/device-agent/requirements-build.lock"
[ -f "$PY_LOCK" ] || fail "requirements-build.lock bulunamadı"
PY_HASH="$( { shasum -a 256 "$PY_LOCK" | cut -d' ' -f1; python3.14 -c 'import sys;print(sys.version)'; } | shasum -a 256 | cut -d' ' -f1)"
PY_MARK="$WT/device-agent/.venv/.mcptoai-lock-hash"
if [ -f "$PY_MARK" ] && [ "$(cat "$PY_MARK")" = "$PY_HASH" ]; then
  echo "Lock değişmedi; mevcut .venv kullanılacak."
else
  echo "Lock değişti ya da .venv yok; temiz kurulum."
  rm -rf "$WT/device-agent/.venv"
  (cd "$WT" && python3.14 device-agent/scripts/setup-build-env.py)
  echo "$PY_HASH" > "$PY_MARK"
fi

# --- 3. Node bağımlılıkları (lock hash'i değişmediyse atla) --------------------
step "Node bağımlılıkları"
NODE_LOCK="$WT/desktop/package-lock.json"
NODE_HASH="$( { shasum -a 256 "$NODE_LOCK" | cut -d' ' -f1; node --version; } | shasum -a 256 | cut -d' ' -f1)"
NODE_MARK="$WT/desktop/node_modules/.mcptoai-lock-hash"
if [ -f "$NODE_MARK" ] && [ "$(cat "$NODE_MARK")" = "$NODE_HASH" ]; then
  echo "package-lock değişmedi; mevcut node_modules kullanılıyor."
else
  (cd "$WT/desktop" && npm ci)
  echo "$NODE_HASH" > "$NODE_MARK"
fi

# Ortam kurulumu çalışma ağacını kirletmemeli.
if [ -n "$(git -C "$WT" status --porcelain)" ]; then
  git -C "$WT" status --porcelain
  fail "ortam kurulumu çalışma ağacını değiştirdi"
fi

# --- 4. Derleme ---------------------------------------------------------------
step "Derleme (notarization: $([ "$NOTARIZE" = 1 ] && echo AÇIK || echo KAPALI))"
export MCPTOAI_RELEASE_BUILD=1
export MCPTOAI_DEVELOPER_ID
if [ "$NOTARIZE" = 1 ]; then
  export MCPTOAI_NOTARY_PROFILE
  unset MCPTOAI_SKIP_NOTARIZE || true
else
  # Not: release-macos.sh bu değişkeni desteklemelidir (bkz. INTEGRATION.md).
  export MCPTOAI_SKIP_NOTARIZE=1
  unset MCPTOAI_NOTARY_PROFILE || true
fi
(cd "$WT/desktop" && ./scripts/release-macos.sh)

# --- 5. Doğrulama ve özet -----------------------------------------------------
step "Doğrulama"
DIST="$WT/desktop/dist"
DMG="$(ls -t "$DIST"/MCPtoAI-*-arm64.dmg 2>/dev/null | head -1 || true)"
[ -n "$DMG" ] || fail "DMG bulunamadı"
APP="$(ls -d "$DIST"/mac-arm64/MCPtoAI.app 2>/dev/null | head -1 || true)"
[ -n "$APP" ] || fail "MCPtoAI.app bulunamadı"
BUILD_INFO="$APP/Contents/Resources/build-info.json"
[ -f "$BUILD_INFO" ] || fail "build-info.json bulunamadı"

BI_COMMIT="$(python3.14 -c 'import json,sys;print(json.load(open(sys.argv[1]))["commit"])' "$BUILD_INFO")"
BI_DIRTY="$(python3.14 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("dirty"))' "$BUILD_INFO")"
# build-info.json sürüm içermiyor; sürüm uygulamanın Info.plist dosyasından okunur.
BI_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"
[ "$BI_COMMIT" = "$SHA" ] || fail "build-info commit uyuşmuyor: $BI_COMMIT"
[ "$BI_DIRTY" = "False" ] || fail "build-info dirty=$BI_DIRTY"

codesign --verify --deep --strict "$APP" || fail "codesign doğrulaması başarısız"
# Not: "grep -m1" erken çıkınca codesign SIGPIPE alır ve pipefail betiği sessizce sonlandırır;
# bu yüzden çıktı önce değişkene alınır, sonra ayrıştırılır. İmza zinciri yalnızca -dvv ile yazılır.
CS_INFO="$(codesign -dvv "$APP" 2>&1 || true)"
SIGNER="$(printf '%s\n' "$CS_INFO" | sed -n 's/^Authority=//p' | sed -n 1p)"
if [ "$NOTARIZE" = 1 ]; then
  spctl -a -vv -t exec "$APP" || fail "Gatekeeper doğrulaması başarısız"
  GATEKEEPER="accepted (notarized)"
else
  GATEKEEPER="notarization yok (yalnızca yerel test)"
fi

ELECTRON_PLIST="$APP/Contents/Frameworks/Electron Framework.framework/Resources/Info.plist"
ELECTRON_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$ELECTRON_PLIST" 2>/dev/null || echo bilinmiyor)"
PY_IN_PKG="$(find "$APP/Contents" \( -name 'libpython3.*' -o -name 'python3.1*' \) -print 2>/dev/null | head -1 || true)"
PY_IN_PKG="${PY_IN_PKG##*/}"   # yol boşluk içerebilir; xargs yerine kabuk ile kısaltılır

OUT="$ROOT/artifacts/$SHORT-$STAMP"
mkdir -p "$OUT"
cp "$DMG" "$OUT/"
for f in "$DIST"/MCPtoAI-*-arm64.zip "$DIST"/MCPtoAI-*-arm64.zip.blockmap "$DIST"/latest-mac.yml; do
  [ -f "$f" ] && cp "$f" "$OUT/"
done
(cd "$OUT" && shasum -a 256 ./* > SHA256SUMS)
DMG_SHA="$(shasum -a 256 "$DMG" | cut -d' ' -f1)"

cat > "$OUT/SUMMARY.txt" <<EOF
MCPtoAI macOS test paketi
-------------------------
Commit        : $SHA
Sürüm         : $BI_VERSION
dirty         : $BI_DIRTY
DMG           : $OUT/$(basename "$DMG")
DMG SHA-256   : $DMG_SHA
İmzalayan     : $SIGNER
Gatekeeper    : $GATEKEEPER
Electron      : $ELECTRON_VERSION
Python (paket): ${PY_IN_PKG:-bilinmiyor}
Log           : $LOG
Oluşturulma   : $STAMP
EOF

step "Özet"
cat "$OUT/SUMMARY.txt"
echo
echo "BAŞARILI. Bu paket yalnızca test içindir; sunucuya, allowlist'e veya OTA'ya konmamalıdır."
