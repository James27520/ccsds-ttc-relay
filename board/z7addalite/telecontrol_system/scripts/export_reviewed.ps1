param([switch]$Reviewed, [string]$VivadoBin = $env:VIVADO_BIN)
$ErrorActionPreference = 'Stop'
if (-not $Reviewed) { throw 'Review the routed reports and manifest, then pass -Reviewed' }
$runRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$manifestPath = Join-Path $runRoot 'SOURCE_MANIFEST.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
function Assert-Frozen {
    foreach ($entry in $manifest.files) {
        $actual = (Get-FileHash -LiteralPath (Join-Path $runRoot $entry.path) -Algorithm SHA256).Hash
        if ($actual -ne $entry.sha256) { throw "Frozen input hash mismatch: $($entry.path)" }
    }
}
Assert-Frozen
if (-not $VivadoBin) {
    $taskTool = Get-Command 'vivado.bat' -ErrorAction Stop
    $VivadoBin = Split-Path -Parent $taskTool.Source
}
$bin = $VivadoBin
if (-not (Test-Path -LiteralPath (Join-Path $bin 'vivado.bat'))) { throw 'VivadoBin does not contain vivado.bat' }
Push-Location $runRoot
try {
    & "$bin\vivado.bat" -mode batch -source (Join-Path $runRoot 'scripts\export_reviewed.tcl') -log (Join-Path $runRoot 'reports\export_reviewed.log') -journal (Join-Path $runRoot 'reports\export_reviewed.jou') -tclargs reviewed
    if ($LASTEXITCODE -ne 0) { throw 'Reviewed bitstream export failed' }
    Assert-Frozen
    $xsa = Join-Path $runRoot 'artifacts\telecontrol_system_final.xsa'
    $initDir = Join-Path $runRoot 'artifacts\ps7_init'
    New-Item -ItemType Directory -Path $initDir -Force | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($xsa)
    try {
        foreach ($entry in $zip.Entries) {
            if ($entry.Name -match '^ps7_init\.(c|h|tcl|html)$') {
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $initDir $entry.Name), $true)
            }
        }
    } finally { $zip.Dispose() }
    foreach ($name in @('ps7_init.c','ps7_init.h','ps7_init.tcl')) {
        if (-not (Test-Path -LiteralPath (Join-Path $initDir $name))) { throw "XSA missing $name" }
    }
    $outputs = @(Get-ChildItem -LiteralPath (Join-Path $runRoot 'artifacts') -File -Recurse | Where-Object Name -ne 'ARTIFACT_MANIFEST.json' | ForEach-Object {
        [ordered]@{ path=$_.FullName.Substring($runRoot.Length+1).Replace('\','/'); sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); bytes=$_.Length }
    })
    [ordered]@{ created_utc=[DateTime]::UtcNow.ToString('o'); part=$manifest.part; source_manifest_sha256=(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant(); files=$outputs } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runRoot 'artifacts\ARTIFACT_MANIFEST.json') -Encoding utf8
    Write-Host "FINAL_EXPORT_COMPLETE=$runRoot\artifacts"
} finally { Pop-Location }
