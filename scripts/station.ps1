param([ValidateSet('1', '2', 'all', 'setup', 'check')][string]$Action = 'check')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$stationPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$pythonProbe = "import sys,struct,tkinter; assert sys.version_info >= (3,11) and struct.calcsize('P')==8; print(sys.executable)"

function Find-StationPython {
    $candidates = @(
        @{ Command = 'py'; Prefix = @('-3.13') },
        @{ Command = 'py'; Prefix = @('-3') },
        @{ Command = 'python'; Prefix = @() }
    )
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) { continue }
        try {
            $prefix = $candidate.Prefix
            $resolved = @(& $candidate.Command @prefix -c $pythonProbe 2>$null)
            if ($LASTEXITCODE -eq 0 -and $resolved.Count) { return [string]$resolved[-1] }
        } catch { continue }
    }
    throw 'Install 64-bit Python 3.13 with pip and Tcl/Tk, then run setup_station.bat again. https://www.python.org/downloads/windows/'
}

try {
    if ($Action -eq 'setup') {
        if (-not (Test-Path -LiteralPath $stationPython)) {
            if (Test-Path -LiteralPath (Join-Path $repoRoot '.venv')) {
                throw 'Existing .venv is incomplete or copied from another PC. Rename that folder and run setup again; do not copy virtual environments.'
            }
            $basePython = Find-StationPython
            & $basePython -m venv (Join-Path $repoRoot '.venv')
            if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python environment.' }
        }
        & $stationPython -c $pythonProbe
        if ($LASTEXITCODE -ne 0) { throw 'Existing .venv is not usable. See docs/two-computer-guide.md.' }
        & $stationPython -m pip install --disable-pip-version-check -r sw/ground_station/requirements-windows.txt
        if ($LASTEXITCODE -ne 0) { throw 'Package installation failed. Check the network and rerun setup_station.bat.' }
    }
    if (-not (Test-Path -LiteralPath $stationPython)) {
        throw 'Run setup_station.bat once before starting this computer.'
    }
    if ($Action -in @('setup', 'check')) {
        & $stationPython -m sw.ground_station.station_environment
    } else {
        & $stationPython -m sw.ground_station.station_environment --quiet
    }
    if ($LASTEXITCODE -ne 0) { throw 'Desktop preflight failed. No board was opened.' }
    if ($Action -eq 'all') {
        & $stationPython -m sw.ground_station.ui_v2 --all --online-business --online-control
    } elseif ($Action -in @('1', '2')) {
        & $stationPython -m sw.ground_station.ui_v2 --computer $Action
    } else {
        Write-Host 'Ready. Computer 1: start_terminal1.bat; Computer 2: start_terminal2.bat.'
        exit 0
    }
    exit $LASTEXITCODE
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
