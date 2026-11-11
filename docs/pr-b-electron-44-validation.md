# PR B — Electron 44 upgrade / release acceptance

## Scope and support

- Electron **41.10.6 → 44.9.3** (published 2026-10-21 UTC; >=14 days old on 2026-11-04; 44.10.2 published 2026-11-03 and deliberately rejected) (exact pin and lockfile); Desktop and Device Agent **0.2.8** so updater and agent handover can detect a newer version.
- Electron supports the latest **three stable major versions**. At preparation time Electron 45 is latest; 44 is supported while 44/45 remain within the newest three, **until Electron 46 becomes stable**. This is a version-based support window, not a guaranteed calendar end date. Reassess before shipping.
- No intentional changes to IPC, handover, supervision, signing or update algorithms.

## Fresh-clone environment

- macOS: install Python **3.14**, Node >=22.12, Xcode Command Line Tools. Run `python3.14 device-agent/scripts/setup-build-env.py`, then `npm ci` in `desktop`; invoke `MCPTOAI_RELEASE_BUILD=1 MCPTOAI_DEVELOPER_ID="Developer ID Application: AHMET BAKTIAYA (WCUHC7RX92)" MCPTOAI_NOTARY_PROFILE=uhm-notary ./scripts/release-macos.sh` from `desktop`. Signed release script handles Developer ID and notarization; no publishing.
- Windows: install Python **3.14** (py launcher), Node >=22.12 and Windows Azure signing prerequisites. Run `py -3.14 device-agent/scripts/setup-build-env.py`, then `npm ci` in `desktop` and `npm run dist:win`. No signing keys are committed.
- `device-agent/requirements-build.lock` is generated with pip-tools on Python 3.14 from `requirements-build.in`; Windows-only `pywin32==311` is installed by the setup script because macOS pip-compile omits Windows-only markers. The setup script validates Python version, runs `pip check`, and verifies PyInstaller. To update lock: `pip-compile --output-file requirements-build.lock requirements-build.in`.

## Test artifact isolation (mandatory)

- All generated test artifacts MUST report **0.2.8** (Desktop and Device Agent). These are private **test-only** builds.
- **NEVER upload to a server, release download directory, allowlist, update feed or OTA endpoint. NEVER publish to GitHub Releases or distribute to production.** `release-macos.sh` signs/notarizes locally; do not perform a separate publishing step.
- The 0.2.7/Electron 41 → 0.2.8/Electron 44 updater migration must use a private isolated test feed, with no production server or allowlist changes.

## Breaking changes reviewed (Electron 42 → 43 → 44)

- **42:** macOS notifications use `UNNotification` and require signed apps; this PR's Developer ID test builds meet that condition. Offscreen rendering defaults to device scale factor 1.0; application does not use offscreen BrowserWindow. Electron binary download moves from npm `postinstall` to first launch; packaging must allow runtime download during build, and must not assume `npm ci` itself installs Electron binary.
- **43:** official breaking-change notes have no direct change to `app.setLoginItemSettings`/`loginItemService`, `safeStorage`, `electron-updater`, BrowserWindow creation or the `ipcMain.handle` / `ipcRenderer.invoke` APIs used here.
- **44:** macOS 12 removed (our `minimumSystemVersion` is already 13.0); Windows ia32 removed (build x64 only). `clipboard` is removed from renderer Electron module and its main API becomes async; renderer uses `navigator.clipboard`, not `require('electron').clipboard`. `select-client-certificate` may receive null `webContents` (we do not register that event). ANGLE shared libraries no longer shipped separately (we do not manage them).
- **Targeted API audit:** `app.setLoginItemSettings({type:'loginItemService', serviceName})`, `getLoginItemSettings`, `requestSingleInstanceLock`, `BrowserWindow`, `contextBridge`/IPC, `electron-updater` all still exist; no documented 42/43/44 signature change in their usage. `contextIsolation:true` and `nodeIntegration:false` are explicit; sandbox defaults were changed before Electron 41, not by 42–44. No custom Electron `protocol` handler and no Electron `safeStorage` usage in Desktop; secrets are stored by Python agent Keychain/Credential Manager. Electron-updater 6.8.9 integration and loginItemService still require signed-package runtime regression.
- Official sources: https://www.electronjs.org/docs/latest/breaking-changes ; https://www.electronjs.org/blog/electron-44-0 ; https://releases.electronjs.org/schedule

## Release acceptance — verify on signed test packages, not assumed from source

1. **Native modules**: check `npm ls` and the packaged app for ABI-bound native modules; rebuild any Electron ABI-dependent module and run packaged app.
2. **Secrets**: test macOS Keychain and Windows Credential Manager get/set with an existing paired account; ensure no prompts/regressions or secret leakage in logs.
3. **macOS**: verify Developer ID signature for app, nested Login Item and bundled agent, hardened runtime/entitlements, notarization/stapling and `spctl`; check `loginItemService` registration and launchd recovery after SIGKILL (but not normal SIGTERM).
4. **Windows**: verify Azure-signed installer and agent (`Get-AuthenticodeSignature`), installer upgrade and UAC flow, supervisor singleton and Job Object cleanup.
5. **Package integrity**: run existing `security:scan:mac` / `security:scan:win`, check `app.asar`, absence of backups/maps, hardened packaging and signature after `afterPack`.
6. **Updater**: install signed **0.2.7 / Electron 41**; publish **0.2.8 / Electron 44** to a test update feed; verify download, signature/integrity, restart, settings persistence and rollback/error behavior. **Do not point production at test feed.**
7. **Lifecycle**: verify single-instance lock, Desktop Quit not stopping agent, Overview Stop, handover marker/version, macOS launchd one connect and Windows supervisor + connect (Job Object), 5 restart cycles, login after sign-out.
8. **Observability**: verify persistent desktop/agent logs, About shows Desktop 0.2.8 / Agent 0.2.8 and update status; verify crash/relaunch logs contain no secrets.

## Source-only checks run for this PR

- `npm ci --ignore-scripts` with Electron 44.9.3 locked; 3 existing package-integrity Node tests passed; JavaScript syntax checks passed.
- Python build environment created from the regenerated lock on macOS Python 3.14; `pip check` passed and PyInstaller 6.16.0 resolved.
- **Not yet validated**: signed macOS/Windows builds, notarization, Azure signature, real updater migration, live Keychain/Credential Manager, real launchd/Job Object behavior. These require user-built signed test packages.

## Python build provenance

Installed 0.2.7/A8 macOS signed bundles inspected: `/Applications/MCPtoAI.app` (commit `3fef17e`, 0.2.7) and `/Applications/MCPtoAI 07.44.13.app` (commit `bbbb773`, 0.2.7) both contain `_internal/python3.14` and `_cffi_backend.cpython-314-darwin.so`. The build lock is therefore regenerated on Python 3.14; setup rejects other interpreter minors and refuses to reuse a mismatched `.venv`. Windows must use Python 3.14 as well.
