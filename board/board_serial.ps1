#=============================================================================
# board_serial.ps1 -- drive the telemetry board's Linux shell over COM12
#
#   powershell -File E:\ccsds_fpga\tools\board_serial.ps1 -Cmd "uname -a"
#   powershell -File E:\ccsds_fpga\tools\board_serial.ps1 -Cmd "ls /sys/bus/iio/devices"
#
# Why this exists
# ---------------
#   Only the JTAG port is plugged on the board (no USB gadget, no Ethernet), so
#   the serial console is the ONLY way to reach the board's Linux -- needed to
#   unbind the ADI drivers before JTAG-programming the pure-PL bitstream,
#   otherwise the Zynq watchdog resets the board ~10 s after programming.
#
# Board console: 115200 8N1, login root / analog (PlutoSDR factory firmware)
#
# WARNING: keep this file PURE ASCII (PowerShell 5.1 reads BOM-less UTF-8 as ANSI).
#=============================================================================
param(
    [string]$Cmd  = "uname -a",
    [string]$CmdFile = "",
    [string]$Port = "COM12",
    [int]$Baud     = 115200,
    [string]$User  = "root",
    [string]$Pass  = "analog",
    [int]$SettleMs = 1500
)

$ErrorActionPreference = 'Stop'

# -CmdFile exists because passing a shell command through PowerShell's -File
# argument parser mangles anything containing $( ) or $var (PowerShell tries to
# expand it itself). Reading the command from a file avoids that entirely.
if ($CmdFile -ne "") {
    if (-not (Test-Path $CmdFile)) { throw "CmdFile not found: $CmdFile" }
    $Cmd = (Get-Content $CmdFile -Raw) -replace "`r?`n", "; "
}
$sp = New-Object System.IO.Ports.SerialPort($Port, $Baud, 'None', 8, 'One')
$sp.ReadTimeout = 800
$sp.NewLine     = "`n"

function Read-For($ms) {
    $end = (Get-Date).AddMilliseconds($ms)
    $sb  = New-Object System.Text.StringBuilder
    while ((Get-Date) -lt $end) {
        try {
            $s = $sp.ReadExisting()
            if ($s) { [void]$sb.Append($s) }
        } catch { }
        Start-Sleep -Milliseconds 60
    }
    return $sb.ToString()
}

function Send-Line($line) {
    $sp.Write($line + "`r`n")
    Start-Sleep -Milliseconds $SettleMs
}

try {
    $sp.Open()
    Write-Host "[serial] $Port open @$Baud"
    Start-Sleep -Milliseconds 500
    $sp.DiscardInBuffer()

    # ---- 1. wake the console, see where we are -------------------------------
    $state = ""
    for ($try = 0; $try -lt 6; $try++) {
        $sp.Write("`r`n")
        Start-Sleep -Milliseconds 700
        $r = Read-For 900
        if     ($r -match 'login:')    { $state = 'login';  break }
        elseif ($r -match '[#\$]\s*$') { $state = 'shell';  break }
        elseif ($r -match 'Password:') { $state = 'passwd'; break }
    }
    Write-Host "[serial] console state = $state"

    # ---- 2. log in if needed -------------------------------------------------
    if ($state -eq 'login') {
        $sp.Write($User + "`r`n"); Start-Sleep -Milliseconds 1500
        $r = Read-For 1500
        if ($r -match 'Password:') {
            $sp.Write($Pass + "`r`n"); Start-Sleep -Milliseconds 2500
            $r = Read-For 1500
        }
    } elseif ($state -eq 'passwd') {
        $sp.Write($Pass + "`r`n"); Start-Sleep -Milliseconds 2500
        $r = Read-For 1500
    }

    # ---- 3. prove we have a shell -------------------------------------------
    # NOTE: the ECHO of the command also contains the marker string, so a plain
    # regex match gives a false positive (hit this once). Require the marker to
    # appear on a line of its own, not as part of the echoed command.
    $sp.Write("echo MARK_9Z7`r`n")
    Start-Sleep -Milliseconds 1200
    $chk = Read-For 1500
    $shellOK = $false
    foreach ($ln in ($chk -split "`r?`n")) {
        if ($ln.Trim() -eq 'MARK_9Z7') { $shellOK = $true; break }
    }
    if (-not $shellOK) {
        Write-Host "[serial] !! no shell -- raw output:"
        ($chk -split "`r?`n") | ForEach-Object { "    $($_.TrimEnd())" }
        exit 2
    }
    Write-Host "[serial] shell OK"

    # ---- 4. run the requested command ---------------------------------------
    Write-Host "[serial] >>> $Cmd"
    $sp.Write($Cmd + "`r`n")
    $out = Read-For 12000
    Write-Host "---- output ----"
    ($out -split "`r?`n") | ForEach-Object { $_.TrimEnd() } | Where-Object { $_ -ne '' } | ForEach-Object { "  $_" }
    Write-Host "---- end ----"
}
finally {
    if ($sp.IsOpen) { $sp.Close() }
    Write-Host "[serial] closed"
}
