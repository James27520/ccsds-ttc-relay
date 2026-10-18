#=============================================================================
# uboot_stop.ps1 -- reboot the board and interrupt u-boot so Linux never starts
#
#   powershell -File E:\ccsds_fpga\tools\uboot_stop.ps1
#
# WHY
# ---
#   Linux's ad9361 / cf_axi_adc / cf_axi_dds drivers reach into the PL over AXI.
#   Once our pure-PL bitstream is loaded there is no AXI slave at 0x79020000 /
#   0x79024000, the access hangs, and the Zynq SWDT (10 s, nowayout=1 -- cannot
#   be disabled, killing the userspace feeder does not help) resets the whole
#   board, which then re-loads the ADI bitstream from boot.bin and destroys our
#   design.
#
#   Measured this session: after `unbind_adi.sh` the board resets ~15 s later
#   anyway (serial showed MARK_A/B/C then silence, then a full clean u-boot
#   restart, RESET_STATUS = 0x00400000, watchdog -t 5 -T 10 /dev/watchdog).
#
#   So do not fight it: stop at the u-boot prompt.  Linux never runs, nothing
#   touches the PL over AXI, and the JTAG/ILA stay alive for as long as we need.
#
# WARNING: keep this file PURE ASCII.
#=============================================================================
param(
    [string]$Port = "COM12",
    [int]$Baud    = 115200
)

$ErrorActionPreference = 'Stop'
$sp = New-Object System.IO.Ports.SerialPort($Port, $Baud, 'None', 8, 'One')
$sp.ReadTimeout = 300
$sp.NewLine = "`n"

$log = New-Object System.Text.StringBuilder

function Pump($ms) {
    $end = (Get-Date).AddMilliseconds($ms)
    while ((Get-Date) -lt $end) {
        try {
            $s = $sp.ReadExisting()
            if ($s) { [void]$script:log.Append($s) }
        } catch { }
        Start-Sleep -Milliseconds 30
    }
}

try {
    $sp.Open()
    Write-Host "[uboot] $Port open"
    Start-Sleep -Milliseconds 400
    $sp.DiscardInBuffer()

    # --- are we already at a u-boot prompt or a login prompt? ----------------
    $sp.Write("`r`n"); Pump 800
    $cur = $script:log.ToString()
    if ($cur -match 'Zynq>|U-Boot>|=>\s*$') {
        Write-Host "[uboot] already at a u-boot prompt"
        exit 0
    }

    # --- trigger a reboot from Linux ----------------------------------------
    Write-Host "[uboot] issuing reboot (login if needed)"
    if ($cur -match 'login:') {
        $sp.Write("root`r`n"); Start-Sleep -Milliseconds 1500
        $r = ""
        try { $r = $sp.ReadExisting() } catch { }
        if ($r -match 'Password:') { $sp.Write("analog`r`n"); Start-Sleep -Milliseconds 2500 }
        Pump 1500
    }
    $sp.Write("reboot`r`n")

    # --- spam keys across the u-boot countdown window ------------------------
    # u-boot prints "Hit any key to stop autoboot:  5  4  3  2  1  0"
    # The Zynq takes ~10 s from 'reboot' to that countdown, so spam for 25 s.
    Write-Host "[uboot] spamming keys for 25 s to catch the countdown ..."
    $end = (Get-Date).AddSeconds(25)
    while ((Get-Date) -lt $end) {
        $sp.Write(" ")
        Pump 120
    }

    $out = $script:log.ToString()
    Write-Host "---- tail of console ----"
    ($out -split "`r?`n") | Where-Object { $_.Trim() -ne '' } | Select-Object -Last 18 | ForEach-Object { "  $($_.TrimEnd())" }
    Write-Host "---- end ----"

    if ($out -match 'Zynq>|U-Boot>|\r\n=>') {
        Write-Host "[uboot] *** AT U-BOOT PROMPT -- Linux will not start ***"
        # make sure the prompt is live
        $sp.Write("`r`n"); Pump 800
        exit 0
    } else {
        Write-Host "[uboot] !! did not clearly reach a u-boot prompt -- see console tail above"
        exit 3
    }
}
finally {
    if ($sp.IsOpen) { $sp.Close() }
    Write-Host "[uboot] closed"
}
