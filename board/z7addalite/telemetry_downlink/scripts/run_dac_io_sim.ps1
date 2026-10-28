param([string]$VivadoBin=$env:VIVADO_BIN,
 [string]$BuildDir=(Join-Path $env:TEMP ('relay_tm_io_'+[guid]::NewGuid().ToString('N'))))
$ErrorActionPreference='Stop'
if (-not $VivadoBin) {$VivadoBin=Split-Path -Parent (Get-Command xvlog.bat -ErrorAction Stop).Source}
$taskRoot=Split-Path $PSScriptRoot -Parent
$BuildDir=[IO.Path]::GetFullPath($BuildDir)
if($BuildDir -match '[^\x00-\x7f]'){throw 'Use an ASCII BuildDir for Vivado'}
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
Copy-Item -LiteralPath (Join-Path $taskRoot 'src/tm_dac_io.v') -Destination $BuildDir
Copy-Item -LiteralPath (Join-Path $taskRoot 'sim/tb_tm_dac_io.sv') -Destination $BuildDir
$taskGlbl=Join-Path $VivadoBin '../../data/verilog/src/glbl.v'
if(!(Test-Path -LiteralPath $taskGlbl)) {$taskGlbl=Join-Path $VivadoBin '../data/verilog/src/glbl.v'}
Push-Location $BuildDir
try {
 & "$VivadoBin/xvlog.bat" --sv tm_dac_io.v tb_tm_dac_io.sv $taskGlbl
 if($LASTEXITCODE){throw 'DAC DDR compile failed'}
 & "$VivadoBin/xelab.bat" -mt 4 tb_tm_dac_io glbl -L unisims_ver -s tm_dac_io_test
 if($LASTEXITCODE){throw 'DAC DDR elaboration failed'}
 & "$VivadoBin/xsim.bat" tm_dac_io_test -runall -log result.log
 if($LASTEXITCODE){throw 'DAC DDR simulation failed'}
 $taskLog=Get-Content -LiteralPath result.log -Raw
 if($taskLog -match 'Fatal:|ERROR:' -or $taskLog -notmatch 'TM_DAC_IO_PASS'){throw 'DAC DDR tests failed'}
} finally {Pop-Location}
