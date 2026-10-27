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
 $taskSources=@('adda_ps_core.c','../software/protocol/adda_protocol.c','../software/demod/adda_demod.c','../software/demod/adda_receiver.c')
 $taskIncludes=@('-I','../software/protocol','-I','../software/demod')
 & "$taskHostBin\gcc.exe" -std=c99 -O2 -Wall -Wextra -Wpedantic -Werror @taskIncludes @taskSources test_ps_core.c -lm -o test_ps_core.exe
 if($LASTEXITCODE-ne 0){throw 'host core compile failed'}
 & .\test_ps_core.exe | Tee-Object -FilePath 'test_results.log'
 if($LASTEXITCODE-ne 0){throw 'host core test failed'}
 New-Item -ItemType Directory -Force -Path 'arm_objects' | Out-Null
 foreach($taskSource in $taskSources) {
  $taskObject='arm_objects/'+[IO.Path]::GetFileNameWithoutExtension($taskSource)+'.o'
  & "$taskArmBin\arm-none-eabi-gcc.exe" -std=c99 -O2 -Wall -Wextra -Werror -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard @taskIncludes -c $taskSource -o $taskObject
  if($LASTEXITCODE-ne 0){throw "A9 object compile failed: $taskSource"}
 }
 'PASS host mock test and Cortex-A9 hard-float compile-only; no firmware link or hardware execution' | Set-Content -LiteralPath 'build_status.txt' -Encoding UTF8
 Get-FileHash -Algorithm SHA256 -LiteralPath adda_ps_core.h,adda_ps_core.c,test_ps_core.c |
  Select-Object Path,Hash | ConvertTo-Json | Set-Content -LiteralPath 'sha256.json' -Encoding UTF8
} finally {Pop-Location}
