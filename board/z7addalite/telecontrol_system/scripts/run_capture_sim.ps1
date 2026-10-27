param([string]$VivadoBin = $env:VIVADO_BIN)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $VivadoBin) {
    $taskTool = Get-Command 'xvlog.bat' -ErrorAction Stop
    $VivadoBin = Split-Path -Parent $taskTool.Source
}
$bin = $VivadoBin
if (-not (Test-Path -LiteralPath (Join-Path $bin 'xvlog.bat'))) { throw 'VivadoBin does not contain xvlog.bat' }
Push-Location (Join-Path $taskRoot 'sim')
try {
  & "$bin\xvlog.bat" --sv -i "$taskRoot\abi" "$taskRoot\src\tc_mailbox.v" "$taskRoot\src\tc_capture_source.v" "$taskRoot\src\tc_capture_control.v" "$taskRoot\src\tc_capture_path.v" "$taskRoot\sim\tb_capture.sv" "$bin\..\data\verilog\src\glbl.v" 2>&1 | Tee-Object capture_compile.log
  if ($LASTEXITCODE -ne 0) { throw 'xvlog failed' }
  & "$bin\xelab.bat" tb_capture glbl -L xpm -L unisims_ver -L secureip -s capture_test --debug typical -mt 4 2>&1 | Tee-Object capture_elaborate.log
  if ($LASTEXITCODE -ne 0) { throw 'xelab failed' }
  & "$bin\xsim.bat" capture_test -runall 2>&1 | Tee-Object capture_test.log
  if ($LASTEXITCODE -ne 0) { throw 'xsim failed' }
  if (-not (Select-String -Path capture_test.log -Pattern 'PASS CAPTURE' -Quiet)) { throw 'PASS absent' }
} finally { Pop-Location }

