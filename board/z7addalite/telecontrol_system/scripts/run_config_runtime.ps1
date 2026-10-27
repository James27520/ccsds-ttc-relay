param([string]$VivadoBin=$env:VIVADO_BIN)
$ErrorActionPreference='Stop'
if (-not $VivadoBin) { $VivadoBin = Split-Path -Parent (Get-Command xvlog.bat -ErrorAction Stop).Source }
$root=Split-Path $PSScriptRoot -Parent
$sim=Join-Path $root 'sim\config_runtime_build'
New-Item -ItemType Directory -Force -Path $sim | Out-Null
Push-Location $sim
try {
 & "$VivadoBin\xvlog.bat" --sv -i "$root\src" "$root\src\spi_rw24.v" "$root\src\tc_boot_config.v" "$root\src\tc_adc_config.v" "$root\sim\tb_config_runtime.sv"
 if($LASTEXITCODE){throw 'Runtime config compile failed'}
 & "$VivadoBin\xelab.bat" -mt 4 -debug typical -timescale 1ns/1ps tb_config_runtime -s config_runtime
 if($LASTEXITCODE){throw 'Runtime config elaboration failed'}
 & "$VivadoBin\xsim.bat" config_runtime -runall -log "$root\sim\config_runtime_test.log"
 if($LASTEXITCODE){throw 'Runtime config simulation failed'}
 $result=Get-Content -Raw -LiteralPath "$root\sim\config_runtime_test.log"
 if($result -match 'Fatal:|ERROR:' -or $result -notmatch 'CONFIG_RUNTIME_PASS'){throw 'Runtime config did not pass'}
} finally {Pop-Location}
