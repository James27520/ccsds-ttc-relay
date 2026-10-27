param(
    [string]$VivadoBin = $env:VIVADO_BIN,
    [string]$OutputRoot = (Join-Path ([IO.Path]::GetTempPath()) ('z7_pn9_' + [Guid]::NewGuid().ToString('N'))),
    [string]$Python = $(if ($env:PYTHON) { $env:PYTHON } else { 'python' }),
    [switch]$UseFrozenFixtures = $true
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
if (-not $VivadoBin) {
    $taskTool = Get-Command xvlog.bat -ErrorAction Stop
    $VivadoBin = Split-Path -Parent $taskTool.Source
}
foreach ($taskTool in @('xvlog.bat','xelab.bat','xsim.bat')) {
    if (-not (Test-Path -LiteralPath (Join-Path $VivadoBin $taskTool))) { throw "Missing Vivado tool: $taskTool" }
}
$taskRun = [IO.Path]::GetFullPath($OutputRoot)
if ($taskRun -match '[^\x00-\x7F]') { throw 'OutputRoot must be ASCII for Vivado on Windows' }
if (Test-Path -LiteralPath $taskRun) { throw 'OutputRoot must be a new directory' }
New-Item -ItemType Directory -Path $taskRun | Out-Null
foreach ($taskDir in @('src','abi','sim')) {
    New-Item -ItemType Directory -Path (Join-Path $taskRun $taskDir) | Out-Null
}
foreach ($taskFile in Get-ChildItem -LiteralPath (Join-Path $taskRoot 'src') -File) { Copy-Item -LiteralPath $taskFile.FullName -Destination (Join-Path $taskRun 'src') }
Copy-Item -LiteralPath (Join-Path $taskRoot 'abi/capture_abi.vh') -Destination (Join-Path $taskRun 'abi')
$bin = $VivadoBin
Copy-Item -LiteralPath (Join-Path $taskRoot 'sim/tb_pn9_train.sv') -Destination (Join-Path $taskRun 'sim')
if ($UseFrozenFixtures) {
    & $Python -B (Join-Path $taskRoot 'scripts/check_frozen_pn9.py') --output (Join-Path $taskRun 'sim/pn9_fixtures')
} else {
    & $Python -B (Join-Path $taskRoot 'scripts/pn9_generate_fixtures.py') --output (Join-Path $taskRun 'sim/pn9_fixtures')
}
if ($LASTEXITCODE -ne 0) { throw 'PN9 fixture validation failed' }
$simDir = Join-Path $taskRun 'sim/pn9_work'
New-Item -ItemType Directory -Path $simDir | Out-Null
Push-Location $simDir
try {
  & "$bin\xvlog.bat" --sv "$taskRun\src\tc_pn9_train.v" "$taskRun\sim\tb_pn9_train.sv" 2>&1 | Tee-Object pn9_compile.log
  if ($LASTEXITCODE -ne 0) { throw 'PN9 xvlog failed' }
  & "$bin\xelab.bat" tb_pn9_train -s pn9_test --debug typical 2>&1 | Tee-Object pn9_elaborate.log
  if ($LASTEXITCODE -ne 0) { throw 'PN9 xelab failed' }
  & "$bin\xsim.bat" pn9_test -runall 2>&1 | Tee-Object pn9_test.log
  if ($LASTEXITCODE -ne 0) { throw 'PN9 xsim failed' }
  if (Select-String -Path pn9_test.log -Pattern 'FAIL PN9|Fatal:|FATAL:|ERROR:' -Quiet) { throw 'PN9 simulation reported a failure' }
  if (-not (Select-String -Path pn9_test.log -Pattern 'PASS PN9 training:' -Quiet)) { throw 'PN9 PASS absent' }
} finally { Pop-Location }
Write-Output "PN9_OUTPUT=$taskRun"
