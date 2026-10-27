param(
    [string]$Compiler = $(if ($env:CC) { $env:CC } else { 'gcc' }),
    [string]$LegacyInclude = $env:ADDA_LEGACY_INCLUDE
)
$ErrorActionPreference = 'Stop'
$taskCompiler = (Get-Command $Compiler -ErrorAction Stop).Source
$taskPriorPath = $env:PATH
$taskOut = Join-Path $PSScriptRoot 'build'
New-Item -ItemType Directory -Path $taskOut -Force | Out-Null
try {
    $env:PATH = (Split-Path -Parent $taskCompiler) + ';' + $env:PATH
    $taskFlags = @('-std=c99','-O2','-Wall','-Wextra','-Wpedantic','-Werror','-Wconversion','-Wshadow','-Wstrict-prototypes')
    $taskExe = Join-Path $taskOut 'test_protocol.exe'
    & $taskCompiler @taskFlags -o $taskExe (Join-Path $PSScriptRoot 'adda_protocol.c') (Join-Path $PSScriptRoot 'test_protocol.c')
    if ($LASTEXITCODE -ne 0) { throw 'C unit test compile failed' }
    & $taskExe
    if ($LASTEXITCODE -ne 0) { throw 'C unit test failed' }
    if ($LegacyInclude) {
        if (-not (Test-Path -LiteralPath (Join-Path $LegacyInclude 'relay_rf_packet.h'))) { throw 'LegacyInclude must contain relay_rf_packet.h' }
        $taskCompat = Join-Path $taskOut 'test_legacy_compat.exe'
        & $taskCompiler @taskFlags -isystem $LegacyInclude -o $taskCompat (Join-Path $PSScriptRoot 'adda_protocol.c') (Join-Path $PSScriptRoot 'test_legacy_compat.c')
        if ($LASTEXITCODE -ne 0) { throw 'Legacy compatibility compile failed' }
        & $taskCompat
        if ($LASTEXITCODE -ne 0) { throw 'Legacy compatibility failed' }
    } else { Write-Output 'SKIP optional legacy compatibility (set -LegacyInclude or ADDA_LEGACY_INCLUDE).' }
} finally { $env:PATH = $taskPriorPath }
