param([string]$taskHostBin=$env:ADDA_HOST_GCC_BIN)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'build_tools.ps1')
$taskHostBin=Resolve-AddaToolDirectory $taskHostBin 'ADDA_HOST_GCC_BIN' 'gcc.exe'
$env:PATH=$taskHostBin+';'+$env:PATH
$taskOut=Join-Path ([IO.Path]::GetTempPath()) ('adda_remote_tests_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskOut | Out-Null
Push-Location $PSScriptRoot
try {
 foreach($taskTest in @('test_remote_control','test_khz_control')) {
  & "$taskHostBin/gcc.exe" -std=c99 -O2 -Wall -Wextra -Wpedantic -Werror -I ../software/protocol -I ../software/demod adda_ps_core.c adda_telemetry_tx.c ../software/protocol/adda_protocol.c ../software/demod/adda_demod.c ../software/demod/adda_receiver.c "$taskTest.c" -lm -o "$taskOut/$taskTest.exe"
  if($LASTEXITCODE-ne 0){throw "$taskTest compile failed"}
  & "$taskOut/$taskTest.exe"
  if($LASTEXITCODE-ne 0){throw "$taskTest failed"}
 }
 Write-Output "Native output=$taskOut; no hardware execution"
} finally {Pop-Location}
