param([string]$taskHostBin=$env:ADDA_HOST_GCC_BIN,[string]$taskArmBin=$env:ADDA_ARM_GCC_BIN)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'build_tools.ps1')
$taskHostBin=Resolve-AddaToolDirectory $taskHostBin 'ADDA_HOST_GCC_BIN' 'gcc.exe'
$taskArmBin=Resolve-AddaToolDirectory $taskArmBin 'ADDA_ARM_GCC_BIN' 'arm-none-eabi-gcc.exe'
$env:PATH=$taskHostBin+';'+$env:PATH
$taskOut=Join-Path ([IO.Path]::GetTempPath()) ('adda_tm_tests_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskOut | Out-Null
Push-Location $PSScriptRoot
try {
 foreach($taskEnabled in @(0,1)) {
  $taskExe=Join-Path $taskOut "telemetry_$taskEnabled.exe"
  & "$taskHostBin/gcc.exe" -std=c99 -O2 -Wall -Wextra -Wpedantic -Werror "-DADDA_TM_TX_ENABLED=$taskEnabled" -I ../software/protocol -I ../software/demod adda_telemetry_tx.c ../software/protocol/adda_protocol.c test_telemetry_tx.c -o $taskExe
  if($LASTEXITCODE-ne 0){throw 'telemetry host compile failed'}
  & $taskExe
  if($LASTEXITCODE-ne 0){throw 'telemetry mock test failed'}
  & "$taskArmBin/arm-none-eabi-gcc.exe" -std=c99 -O2 -Wall -Wextra -Werror -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard "-DADDA_TM_TX_ENABLED=$taskEnabled" -I ../software/protocol -I ../software/demod -c adda_telemetry_tx.c -o (Join-Path $taskOut "telemetry_$taskEnabled.o")
  if($LASTEXITCODE-ne 0){throw 'telemetry A9 compile failed'}
 }
 Write-Output "PASS host mocks and Cortex-A9 compile-only, output=$taskOut; no hardware execution"
} finally {Pop-Location}
