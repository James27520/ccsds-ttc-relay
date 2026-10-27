param(
    [string]$VivadoBin = $env:VIVADO_BIN,
    [string]$OutputRoot = (Join-Path ([IO.Path]::GetTempPath()) ('z7_axil_' + [Guid]::NewGuid().ToString('N'))))
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
Copy-Item -LiteralPath (Join-Path $taskRoot 'sim/tb_axil.sv') -Destination (Join-Path $taskRun 'sim')
Push-Location (Join-Path $taskRun 'sim')
try {
  & "$bin\xvlog.bat" --sv -i "$taskRun\abi" "$taskRun\src\tc_axil_frontend.v" "$taskRun\src\tc_snapshot_ram.v" "$taskRun\sim\tb_axil.sv" 2>&1 | Tee-Object axil_compile.log
  if ($LASTEXITCODE -ne 0) { throw 'xvlog failed' }
  & "$bin\xelab.bat" tb_axil -s axil_test --debug typical -mt 4 2>&1 | Tee-Object axil_elaborate.log
  if ($LASTEXITCODE -ne 0) { throw 'xelab failed' }
  & "$bin\xsim.bat" axil_test -runall 2>&1 | Tee-Object axil_test.log
  if ($LASTEXITCODE -ne 0) { throw 'xsim failed' }
  if (-not (Select-String -Path axil_test.log -Pattern 'PASS AXIL' -Quiet)) { throw 'PASS absent' }
} finally { Pop-Location }


Write-Output "AXIL_OUTPUT=$taskRun"
