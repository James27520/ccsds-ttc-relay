param([string]$RunName = 'r4c', [Parameter(Mandatory=$true)][string]$OutputRoot, [string]$VivadoBin = $env:VIVADO_BIN)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ($RunName -notmatch '^[a-zA-Z0-9_-]+$') { throw 'RunName must be a simple directory name' }
$outputPath = [IO.Path]::GetFullPath($OutputRoot)
if ($outputPath -match '[^\x00-\x7F]') { throw 'OutputRoot must be an ASCII path for Vivado on Windows' }
$runRoot = Join-Path $outputPath $RunName
if (Test-Path -LiteralPath $runRoot) { throw "Run already exists: $runRoot. Choose a fresh RunName." }
if (-not $VivadoBin) {
    $taskTool = Get-Command 'vivado.bat' -ErrorAction Stop
    $VivadoBin = Split-Path -Parent $taskTool.Source
}
$bin = $VivadoBin
if (-not (Test-Path -LiteralPath (Join-Path $bin 'vivado.bat'))) { throw 'VivadoBin does not contain vivado.bat' }
New-Item -ItemType Directory -Path $runRoot | Out-Null
foreach ($dir in @('src','constraints','abi','scripts','vendor','reference')) {
    Copy-Item -LiteralPath (Join-Path $taskRoot $dir) -Destination (Join-Path $runRoot $dir) -Recurse
}
foreach ($dir in @('sim','reports','artifacts','prior_evidence')) {
    New-Item -ItemType Directory -Path (Join-Path $runRoot $dir) | Out-Null
}
Get-ChildItem -LiteralPath (Join-Path $taskRoot 'sim') -Filter '*.sv' | Copy-Item -Destination (Join-Path $runRoot 'sim')
Copy-Item -LiteralPath (Join-Path $taskRoot 'sim\pn9_fixtures') -Destination (Join-Path $runRoot 'sim\pn9_fixtures') -Recurse
$priorLogs = @('sim\axil_test.log','sim\config_runtime_test.log','sim\pn9_work\pn9_test.log','SOURCE_PREBUILD_R1_ACTUAL.json')
foreach ($file in $priorLogs) {
    if (Test-Path -LiteralPath (Join-Path $taskRoot $file)) {
        Copy-Item -LiteralPath (Join-Path $taskRoot $file) -Destination (Join-Path $runRoot 'prior_evidence')
    }
}
function Get-InputManifest {
    $entries = @()
    foreach ($dir in @('src','constraints','abi','scripts','vendor','reference','sim','prior_evidence')) {
        $files = Get-ChildItem -LiteralPath (Join-Path $runRoot $dir) -File -Recurse
        if ($dir -eq 'sim') { $files = $files | Where-Object { $_.Extension -in @('.sv','.mem') -or $_.Name -eq 'pn9_fixture_manifest.json' } }
        foreach ($file in $files) {
            $entries += [ordered]@{ path=$file.FullName.Substring($runRoot.Length+1).Replace('\','/'); sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); bytes=$file.Length }
        }
    }
    return @($entries | Sort-Object { $_.path })
}
$frozen = Get-InputManifest
$manifest = [ordered]@{ created_utc=[DateTime]::UtcNow.ToString('o'); part='xc7z020clg484-2'; source_root=$taskRoot; frozen_root=$runRoot; vivado_bin=$bin; files=$frozen }
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runRoot 'SOURCE_MANIFEST.json') -Encoding utf8
foreach ($entry in $frozen) { (Get-Item -LiteralPath (Join-Path $runRoot $entry.path)).IsReadOnly = $true }
function Assert-FrozenInputs([string]$stage) {
    $current = Get-InputManifest
    $diff = Compare-Object ($frozen | ConvertTo-Json -Depth 5) ($current | ConvertTo-Json -Depth 5)
    if ($diff) { throw "Frozen input changed during $stage" }
    "$(Get-Date -Format o) $stage SHA256_MANIFEST_UNCHANGED=1" | Add-Content -LiteralPath (Join-Path $runRoot 'reports\frozen_integrity.log')
}
Push-Location $runRoot
try {
    & (Join-Path $runRoot 'scripts\run_capture_sim.ps1') -VivadoBin $bin
    Assert-FrozenInputs 'capture_sim'
    & "$bin\vivado.bat" -mode batch -source (Join-Path $runRoot 'scripts\create_platform.tcl') -log (Join-Path $runRoot 'reports\platform.log') -journal (Join-Path $runRoot 'reports\platform.jou')
    if ($LASTEXITCODE -ne 0) { throw 'Platform creation failed' }
    Assert-FrozenInputs 'platform_creation_before_synthesis'
    & "$bin\vivado.bat" -mode batch -source (Join-Path $runRoot 'scripts\build.tcl') -log (Join-Path $runRoot 'reports\build.log') -journal (Join-Path $runRoot 'reports\build.jou')
    if ($LASTEXITCODE -ne 0) { throw 'RTL synthesis/implementation/signoff failed' }
    Assert-FrozenInputs 'post_route_and_xsa'
    Write-Host "FROZEN_BUILD_COMPLETE=$runRoot; bitstream export requires routed-evidence review"
} finally { Pop-Location }
