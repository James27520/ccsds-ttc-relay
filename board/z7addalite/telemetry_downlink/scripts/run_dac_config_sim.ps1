param([string]$VivadoBin=$env:VIVADO_BIN,
 [string]$BuildDir=(Join-Path $env:TEMP ('relay_tm_config_'+[guid]::NewGuid().ToString('N'))))
$ErrorActionPreference='Stop'
if (-not $VivadoBin) {$VivadoBin=Split-Path -Parent (Get-Command xvlog.bat -ErrorAction Stop).Source}
$taskRoot=Split-Path $PSScriptRoot -Parent
$BuildDir=[IO.Path]::GetFullPath($BuildDir)
if($BuildDir -match '[^\x00-\x7f]'){throw 'Use an ASCII BuildDir for Vivado'}
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
foreach($taskFile in @('src/tm_spi16.v','src/tm_dac_config.v','sim/tb_tm_dac_config.sv')) {
 Copy-Item -LiteralPath (Join-Path $taskRoot $taskFile) -Destination $BuildDir
}
Push-Location $BuildDir
try {
 & "$VivadoBin\xvlog.bat" --sv tm_spi16.v tm_dac_config.v tb_tm_dac_config.sv
 if($LASTEXITCODE){throw 'DAC SPI compile failed'}
 & "$VivadoBin\xelab.bat" -mt 4 -debug typical -timescale 1ns/1ps tb_tm_dac_config -s tm_dac_config
 if($LASTEXITCODE){throw 'DAC SPI elaboration failed'}
 & "$VivadoBin\xsim.bat" tm_dac_config -runall -log "$BuildDir\result.log"
 if($LASTEXITCODE){throw 'DAC SPI simulation failed'}
 $taskLog=Get-Content -Raw -LiteralPath "$BuildDir\result.log"
 if($taskLog -match 'Fatal:|ERROR:' -or $taskLog -notmatch 'TM_DAC_CONFIG_PASS'){throw 'DAC SPI tests failed'}
} finally {Pop-Location}
