#=============================================================================
# serial_log.ps1 -- log the telemetry board's console to a file for N seconds
#
#   powershell -File E:\ccsds_fpga\tools\serial_log.ps1 -Seconds 120 -Out E:\ccsds_fpga\out\boot.log
#
# Why: after JTAG-programming the pure-PL bitstream the board was seen to reset
#      (console came back to "pluto login:"). Unbinding the ADI drivers did NOT
#      prevent it this time, so we need the console output captured ACROSS the
#      programming event to see whether it is a watchdog trip, a panic, or a
#      power brown-out.
#
# WARNING: keep this file PURE ASCII.
#=============================================================================
param(
    [string]$Port    = "COM12",
    [int]$Baud       = 115200,
    [int]$Seconds    = 120,
    [string]$Out     = "E:\ccsds_fpga\out\serial.log"
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path (Split-Path $Out -Parent) -Force | Out-Null

$sp = New-Object System.IO.Ports.SerialPort($Port, $Baud, 'None', 8, 'One')
$sp.ReadTimeout = 500
$sw = New-Object System.IO.StreamWriter($Out, $false, (New-Object System.Text.UTF8Encoding($false)))
$sw.AutoFlush = $true

try {
    $sp.Open()
    Write-Host "[serial_log] $Port open, logging ${Seconds}s -> $Out"
    $end = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $end) {
        try {
            $s = $sp.ReadExisting()
            if ($s) { $sw.Write($s) }
        } catch { }
        Start-Sleep -Milliseconds 40
    }
    Write-Host "[serial_log] done"
}
finally {
    try { $sw.Flush(); $sw.Close() } catch { }
    if ($sp.IsOpen) { $sp.Close() }
    Write-Host "[serial_log] closed  ($((Get-Item $Out).Length) bytes)"
}
