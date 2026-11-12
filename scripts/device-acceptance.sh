#!/bin/bash
# MCPtoAI — macOS cihaz kabul testi.
#
# Kullanım:
#   scripts/device-acceptance.sh [--expect-commit <sha>] [--loops N] [--restart-agent] [--strict-logs] [--json <dosya>]
#
# Varsayılan olarak yalnızca OKUMA yapan kontroller çalışır (süreçlere dokunmaz).
#   --loops N        Desktop'ı N kez kapatıp açar; agent PID'inin değişmediğini doğrular.
#   --restart-agent  Agent'ı launchctl kickstart -k ile yeniden başlatır; tek connect ve
#                    MCP alt süreçlerinin çoğalmadığını doğrular.
#   --strict-logs    Test sırasında agent loguna düşen ERROR/Traceback satırlarını hata sayar
#                    (varsayılan: uyarı).
#
# macOS'taki /bin/bash 3.2 ile uyumludur. Çıkış kodu: tüm kontroller geçtiyse 0, değilse 1.

set -u

EXPECT_COMMIT=""
LOOPS=0
RESTART=0
STRICT_LOGS=0
JSON_OUT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --expect-commit) shift; EXPECT_COMMIT="$1" ;;
    --loops) shift; LOOPS="$1" ;;
    --restart-agent) RESTART=1 ;;
    --strict-logs) STRICT_LOGS=1 ;;
    --json) shift; JSON_OUT="$1" ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "Bilinmeyen seçenek: $1" >&2; exit 2 ;;
  esac
  shift
done

APP="/Applications/MCPtoAI.app"
LABEL="com.bkty.mcptoai.device-agent"
AGENT_PATH="$APP/Contents/Library/LoginItems/MCPtoAI Device Agent.app/Contents/Resources/agent/mcptoai-agent"
MARKER="$HOME/.config/mcptoai/desktop-agent-handover.json"
AGENT_LOG="$HOME/Library/Logs/MCPtoAI/agent-error.log"

RESULTS="$(mktemp -t mcptoai-acceptance)"
trap 'rm -f "$RESULTS"' EXIT
FAILED=0

# Sonuç kaydı: ad | durum (pass/fail/warn/skip) | ayrıntı
record() {
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$RESULTS"
  printf '[%s] %s — %s\n' "$2" "$1" "$3"
  [ "$2" = "fail" ] && FAILED=1
  return 0
}

connect_pids() { pgrep -f "mcptoai-agent connect" 2>/dev/null | tr '\n' ' ' | sed 's/ *$//'; }
connect_count() { pgrep -f "mcptoai-agent connect" 2>/dev/null | wc -l | tr -d ' '; }
launchd_pid() { launchctl list 2>/dev/null | awk -v l="$LABEL" '$3==l {print $1}'; }
ppid_of() { ps -o ppid= -p "$1" 2>/dev/null | tr -d ' '; }

# connect'in doğrudan alt süreçlerini "alt komut" adına göre listeler (ör. google-drive-mcp).
children_signature() {
  local parent="$1"
  ps -axo pid=,ppid=,command= 2>/dev/null | awk -v p="$parent" '$2==p {
      cmd=""; for (i=3;i<=NF;i++) cmd=cmd" "$i;
      n=split(cmd, parts, "/"); last=parts[n]; sub(/^ +/, "", last); print last }' | sort
}

wait_single_connect() {
  local i=0
  while [ $i -lt 40 ]; do
    [ "$(connect_count)" = "1" ] && return 0
    sleep 1; i=$((i+1))
  done
  return 1
}

LOG_START_LINES=0
[ -f "$AGENT_LOG" ] && LOG_START_LINES="$(wc -l < "$AGENT_LOG" | tr -d ' ')"

# --- 1. Kurulu uygulama -------------------------------------------------------
if [ -d "$APP" ]; then
  APP_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist" 2>/dev/null)"
  BI_COMMIT="$(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["commit"])' "$APP/Contents/Resources/build-info.json" 2>/dev/null)"
  BI_DIRTY="$(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("dirty"))' "$APP/Contents/Resources/build-info.json" 2>/dev/null)"
  record "app_version" pass "$APP_VERSION"
  if [ -n "$EXPECT_COMMIT" ]; then
    case "$BI_COMMIT" in
      "$EXPECT_COMMIT"*) record "build_commit" pass "$BI_COMMIT" ;;
      *) record "build_commit" fail "beklenen $EXPECT_COMMIT, bulunan $BI_COMMIT" ;;
    esac
  else
    record "build_commit" pass "$BI_COMMIT (beklenen verilmedi)"
  fi
  [ "$BI_DIRTY" = "False" ] && record "build_clean" pass "dirty=False" || record "build_clean" fail "dirty=$BI_DIRTY"
else
  record "app_installed" fail "$APP bulunamadı"
  APP_VERSION=""
fi

# --- 2. Agent süreç modeli ----------------------------------------------------
CNT="$(connect_count)"
PID="$(connect_pids)"
if [ "$CNT" = "1" ]; then
  record "single_connect" pass "PID $PID"
  P="$(ppid_of "$PID")"
  [ "$P" = "1" ] && record "connect_ppid_launchd" pass "PPID 1" || record "connect_ppid_launchd" fail "PPID $P"
  LP="$(launchd_pid)"
  [ "$LP" = "$PID" ] && record "launchd_pid_is_connect" pass "launchd PID $LP" || record "launchd_pid_is_connect" fail "launchd PID '$LP', connect $PID"
  # Uygulama değiştirilince agent dosyası yeni bir inode alır; çalışan süreç eski inode'u kullanmaya devam eder.
  # İkisi farklıysa agent değiştirilmiş dosyalar üzerinde çalışıyordur (yeni modül okurken Error -3 ile çöker).
  # Not: değiştirme zamanı (mtime) güvenilmez; DMG'den kopyalama onu korur.
  DISK_INODE="$(stat -f %i "$AGENT_PATH" 2>/dev/null || echo none)"
  RUN_INODE="$(lsof -a -p "$PID" -d txt -Fin 2>/dev/null | awk -v want="$AGENT_PATH" '/^i/{ino=substr($0,2)} /^n/{if (substr($0,2)==want) {print ino; exit}}')"
  if [ -n "$RUN_INODE" ] && [ "$RUN_INODE" = "$DISK_INODE" ]; then
    record "agent_not_stale" pass "çalışan agent diskteki dosyayla aynı (inode $RUN_INODE)"
  else
    record "agent_not_stale" fail "çalışan agent inode '${RUN_INODE:-bilinmiyor}', diskteki $DISK_INODE: agent değiştirilmiş dosyalar üzerinde çalışıyor"
  fi
  CMD="$(ps -o command= -p "$PID" 2>/dev/null)"
  case "$CMD" in
    "$AGENT_PATH"*) record "agent_path" pass "uygulama paketinin içinden" ;;
    *) record "agent_path" fail "$CMD" ;;
  esac
else
  record "single_connect" fail "$CNT connect süreci: $PID"
fi

# --- 3. Handover marker -------------------------------------------------------
if [ -f "$MARKER" ]; then
  MV="$(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("version",""))' "$MARKER" 2>/dev/null)"
  [ -n "$APP_VERSION" ] && [ "$MV" = "$APP_VERSION" ] && record "handover_marker" pass "$MV" || record "handover_marker" fail "marker '$MV', uygulama '$APP_VERSION'"
else
  record "handover_marker" fail "marker yok: $MARKER"
fi

# --- 4. MCP alt süreçleri (çoğalma yok) ---------------------------------------
if [ "$CNT" = "1" ]; then
  SIG_BEFORE="$(children_signature "$PID")"
  DUP="$(printf '%s\n' "$SIG_BEFORE" | sed '/^$/d' | uniq -d | tr '\n' ' ')"
  KIDS="$(printf '%s\n' "$SIG_BEFORE" | sed '/^$/d' | tr '\n' ',' | sed 's/,$//')"
  [ -z "$DUP" ] && record "mcp_children_unique" pass "${KIDS:-alt süreç yok}" || record "mcp_children_unique" fail "yinelenen: $DUP"
fi

# --- 5. Desktop kapat/aç döngüleri (isteğe bağlı) -----------------------------
if [ "$LOOPS" -gt 0 ] && [ "$CNT" = "1" ]; then
  STABLE=1
  i=1
  while [ $i -le "$LOOPS" ]; do
    osascript -e 'quit app "MCPtoAI"' >/dev/null 2>&1; sleep 5
    Q="$(connect_pids)"
    open "$APP"; sleep 20
    A="$(connect_pids)"
    echo "  döngü $i: önce=$PID kapalı=$Q açık=$A"
    [ "$Q" = "$PID" ] && [ "$A" = "$PID" ] || STABLE=0
    i=$((i+1))
  done
  [ "$STABLE" = 1 ] && record "desktop_quit_loops" pass "$LOOPS döngü, PID $PID sabit" || record "desktop_quit_loops" fail "PID değişti"
elif [ "$LOOPS" -gt 0 ]; then
  record "desktop_quit_loops" skip "tek connect yok"
fi

# --- 6. Agent yeniden başlatma (isteğe bağlı) ---------------------------------
if [ "$RESTART" = 1 ] && [ "$CNT" = "1" ]; then
  OLD="$(connect_pids)"
  launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1
  sleep 3
  if wait_single_connect; then
    NEW="$(connect_pids)"
    if [ "$NEW" != "$OLD" ]; then
      record "restart_single_connect" pass "$OLD → $NEW"
    else
      record "restart_single_connect" fail "PID değişmedi ($NEW)"
    fi
    [ "$(launchd_pid)" = "$NEW" ] && record "restart_launchd_pid" pass "$NEW" || record "restart_launchd_pid" fail "launchd '$(launchd_pid)'"
    sleep 10
    SIG_AFTER="$(children_signature "$NEW")"
    [ "$SIG_AFTER" = "$SIG_BEFORE" ] && record "restart_mcp_children" pass "aynı alt süreç kümesi" \
      || record "restart_mcp_children" fail "önce [$(echo $SIG_BEFORE)] sonra [$(echo $SIG_AFTER)]"
  else
    record "restart_single_connect" fail "40 sn içinde tek connect oluşmadı: $(connect_pids)"
  fi
fi

# --- 7. Test sırasında agent logu ---------------------------------------------
if [ -f "$AGENT_LOG" ]; then
  NEW_ERR="$(tail -n +"$((LOG_START_LINES+1))" "$AGENT_LOG" 2>/dev/null | grep -c -E '\[ERROR\]|Traceback' || true)"
  if [ "$NEW_ERR" = "0" ]; then
    record "agent_log_errors" pass "test sırasında yeni hata yok"
  elif [ "$STRICT_LOGS" = 1 ]; then
    record "agent_log_errors" fail "$NEW_ERR yeni ERROR/Traceback satırı"
  else
    record "agent_log_errors" warn "$NEW_ERR yeni ERROR/Traceback satırı (--strict-logs ile hata sayılır)"
  fi
fi

# --- Sonuç --------------------------------------------------------------------
REPORT="$(/usr/bin/python3 - "$RESULTS" "$FAILED" <<'PY'
import json, sys, platform, datetime
rows = [l.rstrip("\n").split("\t", 2) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
print(json.dumps({
    "platform": "macos",
    "host": platform.node(),
    "time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "result": "fail" if sys.argv[2] == "1" else "pass",
    "checks": [{"name": n, "status": s, "detail": d} for n, s, d in rows],
}, ensure_ascii=False, indent=2))
PY
)"
echo
echo "$REPORT"
[ -n "$JSON_OUT" ] && printf '%s\n' "$REPORT" > "$JSON_OUT"
exit "$FAILED"
