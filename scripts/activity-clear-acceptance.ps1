# Destructive QA wrapper: refuse any profile outside the freshly created root.
param([Parameter(Mandatory=$true)][string]$AgentExe,[string]$PythonExe='python')
$ErrorActionPreference='Stop'
$root=Join-Path ([IO.Path]::GetTempPath()) ('mcptoai-activity-qa-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
New-Item -ItemType File -Path (Join-Path $root '.mcptoai-activity-test-only') | Out-Null
$oldAppData=$env:APPDATA; $oldHome=$env:HOME; $oldPythonPath=$env:PYTHONPATH
try {
  $env:APPDATA=$root
  $env:HOME=$root
  $env:PYTHONPATH=Join-Path (Split-Path -Parent $PSScriptRoot) 'device-agent'
  & $PythonExe -m mcptoai_agent.activity_test_guard $root
  if($LASTEXITCODE -ne 0){throw 'Activity isolation preflight failed; refusing clear'}
  & $AgentExe activity-clear --confirm
  if($LASTEXITCODE -ne 0){throw 'Isolated Activity clear failed'}
} finally {
  $env:APPDATA=$oldAppData; $env:HOME=$oldHome; $env:PYTHONPATH=$oldPythonPath
  Remove-Item -LiteralPath $root -Recurse -Force
}
