param(
 [string]$taskHostBin=$env:ADDA_HOST_GCC_BIN,
 [string]$taskArmBin=$env:ADDA_ARM_GCC_BIN
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'build_tools.ps1')
$taskHostBin=Resolve-AddaToolDirectory $taskHostBin 'ADDA_HOST_GCC_BIN' 'gcc.exe'
$taskArmBin=Resolve-AddaToolDirectory $taskArmBin 'ADDA_ARM_GCC_BIN' 'arm-none-eabi-gcc.exe'
$env:PATH=$taskHostBin+';'+$env:PATH
Push-Location $PSScriptRoot
try {
 $taskSources=@('adda_capture.c','adda_controller.c','adda_ps_core.c','../software/protocol/adda_protocol.c','../software/demod/adda_demod.c','../software/demod/adda_receiver.c','../software/fixtures/generated/waveform_fixture.c')
 $taskIncludes=@('-I','../telecontrol_system/abi','-I','../software/protocol','-I','../software/demod','-I','../software/fixtures/generated')
 & "$taskHostBin\gcc.exe" -std=c99 -O2 -Wall -Wextra -Wpedantic -Werror @taskIncludes @taskSources test_capture_controller.c -lm -o test_capture_controller.exe
 if($LASTEXITCODE-ne 0){throw 'host capture compile failed'}
 & .\test_capture_controller.exe | Tee-Object -FilePath 'capture_test_results.log'
 if($LASTEXITCODE-ne 0){throw 'capture tests failed'}
 New-Item -ItemType Directory -Force -Path 'arm_objects' | Out-Null
 foreach($taskSource in @('adda_capture.c','adda_controller.c','../software/fixtures/generated/waveform_fixture.c')) {
  $taskObject='arm_objects/'+[IO.Path]::GetFileNameWithoutExtension($taskSource)+'.o'
  & "$taskArmBin\arm-none-eabi-gcc.exe" -std=c99 -O2 -Wall -Wextra -Werror -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard @taskIncludes -c $taskSource -o $taskObject
  if($LASTEXITCODE-ne 0){throw "A9 object compile failed: $taskSource"}
 }
 Get-FileHash -Algorithm SHA256 -LiteralPath adda_capture.h,adda_capture.c,adda_controller.h,adda_controller.c,test_capture_controller.c |
   Select-Object Path,Hash | ConvertTo-Json | Set-Content -LiteralPath 'capture_sha256.json' -Encoding UTF8
} finally {Pop-Location}
