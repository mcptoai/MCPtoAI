$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    py -3.14 scripts/setup-build-env.py
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean mcptoai-agent.spec
    & .\dist\mcptoai-agent\mcptoai-agent.exe --help | Out-Null
    & .\.venv\Scripts\python.exe ..\scripts\verify-release-versions.py --agent .\dist\mcptoai-agent\mcptoai-agent.exe --build-info ..\desktop\build-info.json --release
    if ($LASTEXITCODE -ne 0) { throw "Windows agent release version gate failed" }
    Write-Host 'Windows Device Agent build OK'
}
finally {
    Pop-Location
}
