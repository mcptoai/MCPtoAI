$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    if (-not (Test-Path .venv)) { py -3.12 -m venv .venv }
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    & .\.venv\Scripts\python.exe -m pip install -e . pyinstaller
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --name mcptoai-agent --onedir --collect-all keyring --collect-all fastmcp --collect-all mcp --collect-all burner_redis --hidden-import keyring.backends.Windows pyinstaller_entry.py
    & .\dist\mcptoai-agent\mcptoai-agent.exe --help | Out-Null
    Write-Host 'Windows Device Agent build OK'
}
finally {
    Pop-Location
}
