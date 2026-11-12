<#
MCPtoAI — Windows cihaz kabul testi (PowerShell 5.1 uyumlu).

Kullanım:
  powershell -ExecutionPolicy Bypass -File scripts\device-acceptance.ps1 [-ExpectCommit <sha>] [-Loops N] [-RestartAgent] [-StrictLogs] [-JsonOut <dosya>]

Varsayılan olarak yalnızca OKUMA yapan kontroller çalışır (süreçlere dokunmaz).
  -Loops N        Desktop'ı N kez kapatıp açar; supervisor ve connect PID'lerinin değişmediğini doğrular.
  -RestartAgent   connect sürecini sonlandırır; supervisor'ın aynı kalıp tek bir yeni connect
                  başlattığını ve MCP alt süreçlerinin çoğalmadığını doğrular.
  -StrictLogs     Test sırasında agent loguna düşen ERROR/Traceback satırlarını hata sayar (varsayılan: uyarı).

Çıkış kodu: tüm kontroller geçtiyse 0, değilse 1.
#>
param(
    [string]$ExpectCommit = '',
    [int]$Loops = 0,
    [switch]$RestartAgent,
    [switch]$StrictLogs,
    [string]$JsonOut = ''
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$DesktopExe = Join-Path $env:LOCALAPPDATA 'Programs\MCPtoAI\MCPtoAI.exe'
$BuildInfoPath = Join-Path $env:LOCALAPPDATA 'Programs\MCPtoAI\resources\build-info.json'
$AgentExe = Join-Path $env:LOCALAPPDATA 'MCPtoAI\Agent\mcptoai-agent.exe'
$BackgroundExe = Join-Path $env:LOCALAPPDATA 'MCPtoAI\Agent\mcptoai-agent-background.exe'
$Marker = Join-Path $env:APPDATA 'MCPtoAI\desktop-agent-handover.json'
$AgentLog = Join-Path $env:LOCALAPPDATA 'MCPtoAI\Logs\agent-error.log'
$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'

$Checks = New-Object System.Collections.ArrayList
$script:Failed = $false

# Sonuç kaydı: ad, durum (pass/fail/warn/skip), ayrıntı
function Record([string]$Name, [string]$Status, [string]$Detail) {
    [void]$Checks.Add([ordered]@{ name = $Name; status = $Status; detail = $Detail })
    Write-Host ("[{0}] {1} - {2}" -f $Status, $Name, $Detail)
    if ($Status -eq 'fail') { $script:Failed = $true }
}

function Get-AgentProcs([string]$Role) {
    @(Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('mcptoai-agent.exe','mcptoai-agent-background.exe') } |
        Where-Object { $_.CommandLine -match ('\b' + $Role + '\b') })
}

# connect'in doğrudan alt süreçlerini ad + alt komut olarak listeler.
function Get-ChildrenSignature([int]$ParentId) {
    $kids = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentId")
    $names = foreach ($k in $kids) {
        $sub = ''
        if ($k.CommandLine -match '\.exe"?\s+(\S+)') { $sub = $Matches[1] }
        ("{0} {1}" -f $k.Name, $sub).Trim()
    }
    return @($names | Sort-Object)
}

function Wait-SingleConnect([int]$Seconds = 40) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (@(Get-AgentProcs 'connect').Count -eq 1) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

$LogStartLines = 0
if (Test-Path $AgentLog) { $LogStartLines = @(Get-Content $AgentLog).Count }

# --- 1. Kurulu uygulama -------------------------------------------------------
$AppVersion = ''
if (Test-Path $DesktopExe) {
    $rawVersion = (Get-Item $DesktopExe).VersionInfo.ProductVersion
    $AppVersion = (($rawVersion -split '\.') | Select-Object -First 3) -join '.'
    Record 'app_version' 'pass' $AppVersion
    if (Test-Path $BuildInfoPath) {
        $bi = Get-Content $BuildInfoPath -Raw | ConvertFrom-Json
        if ($ExpectCommit) {
            if ($bi.commit.StartsWith($ExpectCommit)) { Record 'build_commit' 'pass' $bi.commit }
            else { Record 'build_commit' 'fail' "beklenen $ExpectCommit, bulunan $($bi.commit)" }
        } else { Record 'build_commit' 'pass' "$($bi.commit) (beklenen verilmedi)" }
        if ($bi.dirty -eq $false) { Record 'build_clean' 'pass' 'dirty=False' } else { Record 'build_clean' 'fail' "dirty=$($bi.dirty)" }
    } else { Record 'build_commit' 'fail' "build-info yok: $BuildInfoPath" }
} else { Record 'app_installed' 'fail' "$DesktopExe bulunamadı" }

# --- 2. Agent süreç modeli (supervisor + tek connect) -------------------------
$Sup = @(Get-AgentProcs 'supervise')
$Con = @(Get-AgentProcs 'connect')
$SupPid = 0; $ConPid = 0
if ($Sup.Count -eq 1) { $SupPid = [int]$Sup[0].ProcessId; Record 'single_supervisor' 'pass' "PID $SupPid" }
else { Record 'single_supervisor' 'fail' "$($Sup.Count) supervisor süreci" }
if ($Con.Count -eq 1) {
    $ConPid = [int]$Con[0].ProcessId
    Record 'single_connect' 'pass' "PID $ConPid"
    if ($SupPid -and [int]$Con[0].ParentProcessId -eq $SupPid) { Record 'connect_under_supervisor' 'pass' "PPID $SupPid" }
    else { Record 'connect_under_supervisor' 'fail' "PPID $($Con[0].ParentProcessId), supervisor $SupPid" }
    # Agent dosyası değiştirildikten sonra eski süreç çalışıyorsa eski kod çalışıyordur.
    $exeTime = (Get-Item $Con[0].ExecutablePath -ErrorAction SilentlyContinue).LastWriteTime
    if ($exeTime -and $Con[0].CreationDate -ge $exeTime) { Record 'agent_not_stale' 'pass' 'agent, agent dosyasından sonra başlamış' }
    else { Record 'agent_not_stale' 'fail' "agent ($($Con[0].CreationDate)) agent dosyasından ($exeTime) önce başlamış" }
    if ($Con[0].ExecutablePath -in @($AgentExe, $BackgroundExe)) { Record 'agent_path' 'pass' $AgentExe }
    else { Record 'agent_path' 'fail' $Con[0].ExecutablePath }
} else { Record 'single_connect' 'fail' "$($Con.Count) connect süreci" }

# --- 3. Oturum açılışı kaydı ve handover marker -------------------------------
$run = (Get-ItemProperty $RunKey -ErrorAction SilentlyContinue).'MCPtoAI Agent'
$task = Get-ScheduledTask -TaskName 'MCPtoAI Agent' -ErrorAction SilentlyContinue
if ($task) {
    $action = @($task.Actions)[0]
    if ($action.Execute -eq $BackgroundExe -and $action.Arguments -eq 'supervise' -and $task.Settings.MultipleInstances -eq 'IgnoreNew' -and @($task.Triggers | Where-Object { $_.Repetition.Interval -eq 'PT5M' -and -not $_.Repetition.Duration -and $_.StartBoundary }).Count -eq 1 -and -not $run) { Record 'scheduled_supervisor' 'pass' $action.Execute }
    else { Record 'scheduled_supervisor' 'fail' "Task=$($action.Execute) Args=$($action.Arguments) Run=$run" }
} elseif ($run -and $run -match 'mcptoai-agent-background\.exe"?\s+supervise\b') { Record 'run_key_supervise' 'warn' "Scheduler unavailable; fallback: $run" }
else { Record 'run_key_supervise' 'fail' "Run kaydı: '$run'" }

if (Test-Path $Marker) {
    $mv = (Get-Content $Marker -Raw | ConvertFrom-Json).version
    if ($AppVersion -and $mv -eq $AppVersion) { Record 'handover_marker' 'pass' $mv }
    else { Record 'handover_marker' 'fail' "marker '$mv', uygulama '$AppVersion'" }
} else { Record 'handover_marker' 'fail' "marker yok: $Marker" }

# --- 4. MCP alt süreçleri (çoğalma yok) ---------------------------------------
$SigBefore = @()
if ($ConPid) {
    $SigBefore = @(Get-ChildrenSignature $ConPid)
    $dups = @($SigBefore | Group-Object | Where-Object { $_.Count -gt 1 } | ForEach-Object { $_.Name })
    $kids = if ($SigBefore.Count) { $SigBefore -join ', ' } else { 'alt süreç yok' }
    if ($dups.Count -eq 0) { Record 'mcp_children_unique' 'pass' $kids }
    else { Record 'mcp_children_unique' 'fail' ("yinelenen: " + ($dups -join ', ')) }
}

# --- 5. Desktop kapat/aç döngüleri (isteğe bağlı) -----------------------------
if ($Loops -gt 0 -and $ConPid -and $SupPid) {
    $stable = $true
    for ($i = 1; $i -le $Loops; $i++) {
        Get-Process MCPtoAI -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 5
        $qs = @(Get-AgentProcs 'supervise' | ForEach-Object { $_.ProcessId }) -join ','
        $qc = @(Get-AgentProcs 'connect' | ForEach-Object { $_.ProcessId }) -join ','
        Start-Process $DesktopExe
        Start-Sleep -Seconds 30
        $as = @(Get-AgentProcs 'supervise' | ForEach-Object { $_.ProcessId }) -join ','
        $ac = @(Get-AgentProcs 'connect' | ForEach-Object { $_.ProcessId }) -join ','
        Write-Host "  döngü $i : supervisor $SupPid/$qs/$as | connect $ConPid/$qc/$ac"
        if ($qs -ne "$SupPid" -or $as -ne "$SupPid" -or $qc -ne "$ConPid" -or $ac -ne "$ConPid") { $stable = $false }
    }
    if ($stable) { Record 'desktop_quit_loops' 'pass' "$Loops döngü, PID'ler sabit" }
    else { Record 'desktop_quit_loops' 'fail' 'PID değişti' }
} elseif ($Loops -gt 0) { Record 'desktop_quit_loops' 'skip' 'supervisor/connect hazır değil' }

# --- 6. Agent yeniden başlatma (isteğe bağlı) ---------------------------------
if ($RestartAgent -and $ConPid -and $SupPid) {
    Stop-Process -Id $ConPid -Force
    Start-Sleep -Seconds 3
    if (Wait-SingleConnect 40) {
        $new = @(Get-AgentProcs 'connect')[0]
        $sup2 = @(Get-AgentProcs 'supervise')
        if ([int]$new.ProcessId -ne $ConPid -and [int]$new.ParentProcessId -eq $SupPid -and $sup2.Count -eq 1) {
            Record 'restart_single_connect' 'pass' "$ConPid → $($new.ProcessId), supervisor $SupPid aynı"
        } else {
            Record 'restart_single_connect' 'fail' "yeni connect $($new.ProcessId), PPID $($new.ParentProcessId), supervisor sayısı $($sup2.Count)"
        }
        Start-Sleep -Seconds 10
        $SigAfter = @(Get-ChildrenSignature ([int]$new.ProcessId))
        if (($SigAfter -join '|') -eq ($SigBefore -join '|')) { Record 'restart_mcp_children' 'pass' 'aynı alt süreç kümesi' }
        else { Record 'restart_mcp_children' 'fail' ("önce [" + ($SigBefore -join ', ') + "] sonra [" + ($SigAfter -join ', ') + "]") }
    } else {
        Record 'restart_single_connect' 'fail' '40 sn içinde tek connect oluşmadı'
    }
}

# --- 7. Test sırasında agent logu ---------------------------------------------
if (Test-Path $AgentLog) {
    $lines = @(Get-Content $AgentLog)
    $newLines = @()
    if ($lines.Count -gt $LogStartLines) { $newLines = $lines[$LogStartLines..($lines.Count - 1)] }
    $errCount = @($newLines | Where-Object { $_ -match '\[ERROR\]|Traceback' }).Count
    if ($errCount -eq 0) { Record 'agent_log_errors' 'pass' 'test sırasında yeni hata yok' }
    elseif ($StrictLogs) { Record 'agent_log_errors' 'fail' "$errCount yeni ERROR/Traceback satırı" }
    else { Record 'agent_log_errors' 'warn' "$errCount yeni ERROR/Traceback satırı (-StrictLogs ile hata sayılır)" }
}

# --- Sonuç --------------------------------------------------------------------
$result = 'pass'
if ($script:Failed) { $result = 'fail' }
$report = [ordered]@{
    platform = 'windows'
    host     = $env:COMPUTERNAME
    time_utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    result   = $result
    checks   = $Checks
}
$json = $report | ConvertTo-Json -Depth 5
Write-Host ''
Write-Host $json
if ($JsonOut) { Set-Content -Path $JsonOut -Value $json -Encoding UTF8 }
if ($script:Failed) { exit 1 } else { exit 0 }
