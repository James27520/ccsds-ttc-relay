param([string]$taskHostBin=$env:ADDA_HOST_GCC_BIN)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'build_tools.ps1')
$taskHostBin=Resolve-AddaToolDirectory $taskHostBin 'ADDA_HOST_GCC_BIN' 'gcc.exe'
$env:PATH=$taskHostBin+';'+$env:PATH
$taskOut=Join-Path ([IO.Path]::GetTempPath()) ('adda_service_tests_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $taskOut | Out-Null
Push-Location $PSScriptRoot
try {
 $taskExe=Join-Path $taskOut 'service.exe'
 & "$taskHostBin/gcc.exe" -std=c99 -O2 -Wall -Wextra -Wpedantic -Werror -DADDA_TM_TX_ENABLED=1 -I ../telecontrol_system/abi -I ../software/protocol -I ../software/demod -I ../software/fixtures/generated adda_service.c adda_controller.c adda_ps_core.c adda_telemetry_tx.c ../software/protocol/adda_protocol.c test_service.c -lm -o $taskExe
 if($LASTEXITCODE-ne 0){throw 'service host compile failed'}
 & $taskExe
 if($LASTEXITCODE-ne 0){throw 'service host tests failed'}
 foreach($taskEnabled in @(0,1)) {
  $taskTmExe=Join-Path $taskOut "telemetry_$taskEnabled.exe"
  & "$taskHostBin/gcc.exe" -std=c99 -O2 -Wall -Wextra -Wpedantic -Werror "-DADDA_TM_TX_ENABLED=$taskEnabled" -I ../software/protocol -I ../software/demod adda_telemetry_tx.c ../software/protocol/adda_protocol.c test_telemetry_tx.c -o $taskTmExe
  if($LASTEXITCODE-ne 0){throw 'telemetry host regression compile failed'}
  & $taskTmExe
  if($LASTEXITCODE-ne 0){throw 'telemetry host regression failed'}
 }
 $taskCaptureExe=Join-Path $taskOut 'capture.exe'
 & "$taskHostBin/gcc.exe" -std=c99 -O2 -Wall -Wextra -Wpedantic -Werror -I ../telecontrol_system/abi -I ../software/protocol -I ../software/demod -I ../software/fixtures/generated adda_capture.c adda_controller.c adda_ps_core.c ../software/protocol/adda_protocol.c ../software/demod/adda_demod.c ../software/demod/adda_receiver.c ../software/fixtures/generated/waveform_fixture.c test_capture_controller.c -lm -o $taskCaptureExe
 if($LASTEXITCODE-ne 0){throw 'manual capture/controller host regression compile failed'}
 & $taskCaptureExe
 if($LASTEXITCODE-ne 0){throw 'manual capture/controller host regression failed'}
 Write-Output "PASS host service mocks only, output=$taskOut; no ARM build or hardware execution"
} finally {Pop-Location}
