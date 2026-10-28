param([Parameter(Mandatory=$true)][string]$OutputRoot,
 [string]$VivadoBin=$env:VIVADO_BIN,[string]$Python='python')
$ErrorActionPreference='Stop'
$taskScripts=$PSScriptRoot
if (-not $VivadoBin) {$VivadoBin=Split-Path -Parent (Get-Command vivado.bat -ErrorAction Stop).Source}
if (-not (Test-Path -LiteralPath (Join-Path $VivadoBin 'vivado.bat'))) {throw 'Missing vivado.bat'}
& $Python (Join-Path $taskScripts 'prepare_build.py') --out $OutputRoot
if ($LASTEXITCODE -ne 0) {throw 'Candidate source preparation failed'}
$taskRun=[IO.Path]::GetFullPath($OutputRoot)
$taskManifest=Get-Content -LiteralPath (Join-Path $taskRun 'SOURCE_MANIFEST.json') -Raw | ConvertFrom-Json
function Assert-Inputs {
 foreach ($entry in $taskManifest.files) {
  if ((Get-FileHash -LiteralPath (Join-Path $taskRun $entry.path) -Algorithm SHA256).Hash -ne $entry.sha256) {throw "Input changed: $($entry.path)"}
 }
}
Push-Location $taskRun
try {
 & (Join-Path $taskRun 'scripts/run_capture_sim.ps1') -VivadoBin $VivadoBin
 if ($LASTEXITCODE -ne 0) {throw 'Capture regression failed'}
 Assert-Inputs
 foreach ($stage in @('create_platform','build')) {
  & (Join-Path $VivadoBin 'vivado.bat') -mode batch -source "scripts/$stage.tcl" -log "reports/$stage.log" -journal "reports/$stage.jou"
  if ($LASTEXITCODE -ne 0) {throw "$stage failed; no release permitted"}
  Assert-Inputs
 }
 Write-Output "ROUTED_CANDIDATE=$taskRun; review base and TM signoff/CDC before export_reviewed.ps1 -Reviewed"
} finally {Pop-Location}
