param(
    [string]$Compiler = $(if ($env:CC) { $env:CC } else { 'gcc' }),
    [string]$Python = $(if ($env:PYTHON) { $env:PYTHON } else { 'python' }),
    [string]$Reference = (Join-Path $PSScriptRoot '..\..\..\..\sw\ccsds\ccsds_tm_tx.py'),
    [string]$ArmCompiler
)
$ErrorActionPreference = 'Stop'
$taskCompiler = (Get-Command $Compiler -ErrorAction Stop).Source
$taskPriorPath = $env:PATH
$taskOut = Join-Path $PSScriptRoot 'build'
New-Item -ItemType Directory -Path $taskOut -Force | Out-Null
try {
    $env:PATH = (Split-Path -Parent $taskCompiler) + ';' + $env:PATH
    $taskSources = @((Join-Path $PSScriptRoot 'adda_demod.c'), (Join-Path $PSScriptRoot 'adda_receiver.c'), (Join-Path $PSScriptRoot '..\protocol\adda_protocol.c'))
    $taskLibrary = Join-Path $taskOut 'adda_receiver.dll'
    & $taskCompiler -std=c99 -Wall -Wextra -Werror -O2 -shared -o $taskLibrary @taskSources -lm
    if ($LASTEXITCODE -ne 0) { throw 'Host compilation failed' }
    & $Python -B (Join-Path $PSScriptRoot 'test_waveforms.py') --reference $Reference --library $taskLibrary --results (Join-Path $taskOut 'waveform_test_results.json')
    if ($LASTEXITCODE -ne 0) { throw 'Waveform tests failed' }
    if ($ArmCompiler) {
        foreach ($taskSource in $taskSources) {
            $taskObject = Join-Path $taskOut ([IO.Path]::GetFileNameWithoutExtension($taskSource) + '.o')
            & $ArmCompiler -std=c99 -Wall -Wextra -Werror -O2 -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard -c $taskSource -o $taskObject
            if ($LASTEXITCODE -ne 0) { throw "ARM compilation failed: $taskSource" }
        }
        Write-Output 'Cortex-A9 objects compiled; this does not prove board execution.'
    }
} finally { $env:PATH = $taskPriorPath }
