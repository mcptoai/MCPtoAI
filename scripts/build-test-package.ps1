<#
MCPtoAI — Windows test paketi derleme betiği (PowerShell 5.1 uyumlu).

Kullanım:
  powershell -ExecutionPolicy Bypass -File scripts\build-test-package.ps1 -Commit <sha|tag> [-Remote <git-url>] [-Root <klasör>]

Ne yapar:
  1. Tek bir kalıcı klonu günceller, kalıcı derleme worktree'sini istenen commit'e geçirir.
  2. Lock dosyası değiştiyse .venv'i siler (temiz kurulum); package-lock değişmediyse npm ci atlanır.
  3. MCPTOAI_RELEASE_BUILD=1 ile npm run dist:win ve güvenlik taramasını çalıştırır.
  4. İmzaları ve build-info'yu doğrular; özeti artifacts\<commit>-<zaman>\SUMMARY.txt dosyasına yazar.

Herhangi bir adım başarısız olursa betik durur.
#>
param(
    [Parameter(Mandatory = $true)][string]$Commit,
    [string]$Remote = $env:MCPTOAI_CORE_REMOTE,
    [string]$Root = $env:MCPTOAI_BUILD_ROOT
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
if (-not $Remote) { $Remote = 'https://github.com/mcptoai/MCPtoAI_Core.git' }
if (-not $Root) { $Root = Join-Path $env:USERPROFILE 'MCP\build-root' }

$Repo = Join-Path $Root 'core-main'      # Tek kalıcı klon
$Wt = Join-Path $Root 'build-wt'         # Kalıcı derleme worktree'si (yol sabit kalır)
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'artifacts'), (Join-Path $Root 'logs') | Out-Null
$Log = Join-Path $Root "logs\build-$Stamp.log"
Start-Transcript -Path $Log | Out-Null

function Step([string]$Text) { Write-Host ''; Write-Host "=== $Text ===" }
function Fail([string]$Text) { Stop-Transcript | Out-Null; throw "HATA: $Text" }

# Dış programı çalıştırır; çıkış kodu sıfır değilse durur.
# PowerShell 5.1'de stderr'e yazan programlar hata sayılmasın diye geçici olarak Continue kullanılır.
function Invoke-Native {
    param([string]$File, [string[]]$Arguments, [string]$Dir = (Get-Location).Path)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $Dir
    try {
        & $File @Arguments
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $prev
    }
    if ($code -ne 0) { Fail "$File $($Arguments -join ' ') (çıkış kodu $code)" }
}

# Dış programın çıktısını döndürür; çıkış kodu sıfır değilse durur.
function Get-NativeOutput {
    param([string]$File, [string[]]$Arguments, [string]$Dir = (Get-Location).Path)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $Dir
    try {
        $out = & $File @Arguments
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $prev
    }
    if ($code -ne 0) { Fail "$File $($Arguments -join ' ') (çıkış kodu $code)" }
    return ($out -join "`n").Trim()
}

function Get-TextHash([string]$Text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLower()
}

# --- Ön koşullar ----------------------------------------------------------------
Invoke-Native 'py' @('-3.14', '--version')
Invoke-Native 'npm' @('--version')

# --- 1. Kaynak ----------------------------------------------------------------
Step "Kaynak: $Commit"
if (-not (Test-Path (Join-Path $Repo '.git'))) {
    Invoke-Native 'git' @('clone', $Remote, $Repo)
}
Invoke-Native 'git' @('-C', $Repo, 'fetch', '--tags', '--prune', 'origin')
$Sha = Get-NativeOutput 'git' @('-C', $Repo, 'rev-parse', '--verify', "$Commit^{commit}")
$Short = $Sha.Substring(0, 7)
Write-Host "Commit: $Sha"

if (-not (Test-Path (Join-Path $Wt '.git'))) {
    Invoke-Native 'git' @('-C', $Repo, 'worktree', 'add', '--detach', $Wt, $Sha)
} else {
    # Kalıcı worktree: önceki derlemenin çıktılarını temizle, ortamları koru.
    Invoke-Native 'git' @('-C', $Wt, 'checkout', '--detach', '--force', $Sha)
    Invoke-Native 'git' @('-C', $Wt, 'clean', '-xfd', '-e', 'device-agent/.venv', '-e', 'desktop/node_modules')
}
if ((Get-NativeOutput 'git' @('-C', $Wt, 'rev-parse', 'HEAD')) -ne $Sha) { Fail 'worktree beklenen commit''te değil' }
$status = Get-NativeOutput 'git' @('-C', $Wt, 'status', '--porcelain')
if ($status) { Write-Host $status; Fail 'çalışma ağacı temiz değil' }

# --- 2. Python ortamı ----------------------------------------------------------
# build-windows.ps1, setup-build-env.py ile mevcut .venv'i yeniden kullanır.
# Lock değiştiyse eski paketler kalmasın diye .venv silinir.
Step 'Python derleme ortamı'
$PyLock = Join-Path $Wt 'device-agent\requirements-build.lock'
if (-not (Test-Path $PyLock)) { Fail 'requirements-build.lock bulunamadı' }
$PyVersion = Get-NativeOutput 'py' @('-3.14', '-c', 'import sys;print(sys.version)')
$PyHash = Get-TextHash ((Get-FileHash $PyLock -Algorithm SHA256).Hash + $PyVersion)
$Venv = Join-Path $Wt 'device-agent\.venv'
$PyMark = Join-Path $Venv '.mcptoai-lock-hash'
$PyFresh = $false
if ((Test-Path $PyMark) -and ((Get-Content $PyMark -Raw).Trim() -eq $PyHash)) {
    Write-Host 'Lock değişmedi; mevcut .venv kullanılacak.'
} else {
    Write-Host 'Lock değişti ya da .venv yok; temiz kurulum.'
    if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
    Invoke-Native 'py' @('-3.14', 'device-agent\scripts\setup-build-env.py') $Wt
    $PyFresh = $true
}
if ($PyFresh) { Set-Content -Path $PyMark -Value $PyHash -Encoding ASCII }

# --- 3. Node bağımlılıkları ----------------------------------------------------
Step 'Node bağımlılıkları'
$NodeLock = Join-Path $Wt 'desktop\package-lock.json'
$NodeVersion = Get-NativeOutput 'node' @('--version')
$NodeHash = Get-TextHash ((Get-FileHash $NodeLock -Algorithm SHA256).Hash + $NodeVersion)
$NodeMark = Join-Path $Wt 'desktop\node_modules\.mcptoai-lock-hash'
if ((Test-Path $NodeMark) -and ((Get-Content $NodeMark -Raw).Trim() -eq $NodeHash)) {
    Write-Host 'package-lock değişmedi; mevcut node_modules kullanılacak.'
} else {
    Invoke-Native 'npm' @('ci') (Join-Path $Wt 'desktop')
    Set-Content -Path $NodeMark -Value $NodeHash -Encoding ASCII
}

$status = Get-NativeOutput 'git' @('-C', $Wt, 'status', '--porcelain')
if ($status) { Write-Host $status; Fail 'ortam kurulumu çalışma ağacını değiştirdi' }

# --- 4. Derleme ---------------------------------------------------------------
Step 'Derleme'
$env:MCPTOAI_RELEASE_BUILD = '1'
$Desktop = Join-Path $Wt 'desktop'
Invoke-Native 'npm' @('run', 'dist:win') $Desktop
Invoke-Native 'npm' @('run', 'security:scan:win') $Desktop

# --- 5. Doğrulama ve özet -----------------------------------------------------
Step 'Doğrulama'
$Dist = Join-Path $Desktop 'dist'
$Setup = Get-ChildItem $Dist -Filter 'MCPtoAI-*-x64-Setup.exe' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Setup) { Fail 'Setup.exe bulunamadı' }
$Unpacked = Join-Path $Dist 'win-unpacked'
$BuildInfoPath = Join-Path $Unpacked 'resources\build-info.json'
if (-not (Test-Path $BuildInfoPath)) { Fail 'build-info.json bulunamadı' }
$BuildInfo = Get-Content $BuildInfoPath -Raw | ConvertFrom-Json
if ($BuildInfo.commit -ne $Sha) { Fail "build-info commit uyuşmuyor: $($BuildInfo.commit)" }
if ($BuildInfo.dirty -ne $false) { Fail "build-info dirty=$($BuildInfo.dirty)" }

$Version = (Get-Item (Join-Path $Unpacked 'MCPtoAI.exe')).VersionInfo.ProductVersion
$SetupSig = Get-AuthenticodeSignature $Setup.FullName
$AgentExe = Join-Path $Unpacked 'resources\agent\mcptoai-agent.exe'
$AgentSig = Get-AuthenticodeSignature $AgentExe
$BackgroundExe = Join-Path $Unpacked 'resources\agent\mcptoai-agent-background.exe'
if (-not (Test-Path $BackgroundExe)) { Fail 'Background Agent EXE bulunamadı' }
$BackgroundSig = Get-AuthenticodeSignature $BackgroundExe
if ($BackgroundSig.Status -ne 'Valid') { Fail "Background Agent imzası: $($BackgroundSig.Status)" }
if ($SetupSig.Status -ne 'Valid') { Fail "Setup imzası: $($SetupSig.Status)" }
if ($AgentSig.Status -ne 'Valid') { Fail "Agent imzası: $($AgentSig.Status)" }
if (-not $SetupSig.TimeStamperCertificate) { Fail 'Setup imzasında zaman damgası yok' }

$ElectronPkg = Join-Path $Desktop 'node_modules\electron\package.json'
$ElectronVersion = 'bilinmiyor'
if (Test-Path $ElectronPkg) { $ElectronVersion = (Get-Content $ElectronPkg -Raw | ConvertFrom-Json).version }
$PyDll = Get-ChildItem (Join-Path $Unpacked 'resources\agent') -Recurse -Filter 'python3*.dll' |
    Where-Object { $_.Name -ne 'python3.dll' } | Select-Object -First 1 -ExpandProperty Name

$Out = Join-Path $Root "artifacts\$Short-$Stamp"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Copy-Item $Setup.FullName $Out
foreach ($name in @("$($Setup.Name).blockmap", 'latest.yml')) {
    $p = Join-Path $Dist $name
    if (Test-Path $p) { Copy-Item $p $Out }
}
$Sums = Get-ChildItem $Out -File | ForEach-Object { "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())  $($_.Name)" }
Set-Content -Path (Join-Path $Out 'SHA256SUMS') -Value $Sums -Encoding ASCII
$SetupHash = (Get-FileHash $Setup.FullName -Algorithm SHA256).Hash.ToLower()

$Summary = @"
MCPtoAI Windows test paketi
---------------------------
Commit          : $Sha
Sürüm           : $Version
dirty           : $($BuildInfo.dirty)
Setup.exe       : $(Join-Path $Out $Setup.Name)
Setup SHA-256   : $SetupHash
Setup imzası    : $($SetupSig.Status) — $($SetupSig.SignerCertificate.Subject)
Zaman damgası   : $($SetupSig.TimeStamperCertificate.Subject)
Agent imzası    : $($AgentSig.Status)
Electron        : $ElectronVersion
Python (paket)  : $PyDll
Log             : $Log
Oluşturulma     : $Stamp
"@
Set-Content -Path (Join-Path $Out 'SUMMARY.txt') -Value $Summary -Encoding UTF8

Step 'Özet'
Write-Host $Summary
Write-Host ''
Write-Host 'BAŞARILI. Bu paket yalnızca test içindir; sunucuya, allowlist''e veya OTA''ya konmamalıdır.'
Stop-Transcript | Out-Null
