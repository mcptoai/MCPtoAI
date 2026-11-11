$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    py -3.14 scripts/setup-build-env.py
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean mcptoai-agent.spec
    & .\dist\mcptoai-agent\mcptoai-agent.exe --help | Out-Null
    Write-Host 'Windows Device Agent build OK'
}
finally {
    Pop-Location
}
