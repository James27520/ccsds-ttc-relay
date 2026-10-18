# board_ssh2.ps1 -- run commands on the telemetry board (192.168.2.1) via plink
#
# Why plink and not ssh.exe:
#   The board's dropbear only accepts keys, and the board rootfs does not carry
#   our public key, so "ssh -i ..." fails with Permission denied (publickey,password).
#   plink can log in with a password, so we use plink.
#
# IMPORTANT: the board regenerates its SSH host key on every boot, so this script
# auto-detects the current fingerprint on each run. Never hardcode it.
#
# Usage:
#   .\board_ssh2.ps1 -Cmd "uname -a"
#   .\board_ssh2.ps1 -CmdFile E:\path\cmds.sh
#
# NOTE: keep this file PURE ASCII with CRLF line endings.

param(
    [string]$Cmd = "",
    [string]$CmdFile = "",
    [string]$Board = "root@192.168.2.1",
    [string]$Password = "analog"
)

$plink = "D:\PuTTY\plink.exe"
if (-not (Test-Path $plink)) {
    $c = Get-Command plink -ErrorAction SilentlyContinue
    if ($c) { $plink = $c.Source } else { Write-Error "plink.exe not found"; exit 2 }
}

if ($CmdFile -ne "") {
    if (-not (Test-Path $CmdFile)) { Write-Error "missing $CmdFile"; exit 2 }
    $Cmd = [IO.File]::ReadAllText($CmdFile)
}
if ($Cmd -eq "") { Write-Error "need -Cmd or -CmdFile"; exit 2 }

function Run-Plink([string[]]$Extra) {
    $a = @("-ssh", "-batch") + $Extra + @("-pw", $Password, $Board)
    $r = & $plink @a "echo __PROBE__" 2>&1
    return $r
}

# Step 1: probe without a host key to learn the current fingerprint
$probe = & $plink -ssh -batch -pw $Password $Board "echo __PROBE__" 2>&1
$txt = (($probe | ForEach-Object { if ($null -ne $_) { $_.ToString() } }) -join "`n")
$m = [regex]::Match($txt, 'SHA256:[A-Za-z0-9+/=]+')
if (-not $m.Success) {
    # No fingerprint in the output: either the key is already cached and it
    # worked, or it failed some other way. Report whatever we got.
    if ($txt -match '__PROBE__') { }
    else { $txt; exit 1 }
    $fp = $null
} else {
    $fp = $m.Value
}

# Step 2: run the real command
if ($fp) {
    $out = & $plink -ssh -batch -hostkey $fp -pw $Password $Board $Cmd 2>&1
} else {
    $out = & $plink -ssh -batch -pw $Password $Board $Cmd 2>&1
}
$out | ForEach-Object { if ($null -ne $_) { $_.ToString().TrimEnd() } }
exit 0
