param(
 [string]$VivadoBin=$env:VIVADO_BIN,
 [string]$BuildDir=(Join-Path $env:TEMP ('relay_tm_packet_'+[guid]::NewGuid().ToString('N')))
)
$ErrorActionPreference='Stop'
if (-not $VivadoBin) {$VivadoBin=Split-Path -Parent (Get-Command xvlog.bat -ErrorAction Stop).Source}
$taskRoot=Split-Path $PSScriptRoot -Parent
$boardRoot=Split-Path $taskRoot -Parent
$mailboxSource=Join-Path $taskRoot 'src\tc_mailbox.v'
if(!(Test-Path -LiteralPath $mailboxSource)) {
 $mailboxSource=Join-Path $boardRoot 'telecontrol_system\src\tc_mailbox.v'
}
$BuildDir=[IO.Path]::GetFullPath($BuildDir)
if($BuildDir -match '[^\x00-\x7f]'){throw 'Vivado simulation needs an ASCII BuildDir; pass -BuildDir with an ASCII path'}
foreach($tool in @('xvlog.bat','xelab.bat','xsim.bat')) {
 if(!(Test-Path -LiteralPath (Join-Path $VivadoBin $tool))){throw "Missing $tool; pass -VivadoBin for the installed Vivado bin directory"}
}
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
# Stage sources so repository paths containing Unicode work with XSIM too.
Copy-Item -LiteralPath $mailboxSource -Destination "$BuildDir\tc_mailbox.v"
Copy-Item -LiteralPath "$taskRoot\src\tm_packet_tx.v" -Destination "$BuildDir\tm_packet_tx.v"
Copy-Item -LiteralPath "$taskRoot\sim\tb_tm_packet_tx.sv" -Destination "$BuildDir\tb_tm_packet_tx.sv"
Push-Location $BuildDir
try {
 & "$VivadoBin\xvlog.bat" --sv tc_mailbox.v tm_packet_tx.v tb_tm_packet_tx.sv
 if($LASTEXITCODE){throw 'Packet engine compile failed'}
 & "$VivadoBin\xelab.bat" -mt 4 -debug typical -timescale 1ns/1ps tb_tm_packet_tx -s tm_packet_tx_sim
 if($LASTEXITCODE){throw 'Packet engine elaboration failed'}
 & "$VivadoBin\xsim.bat" tm_packet_tx_sim -runall -log "$BuildDir\result.log"
 if($LASTEXITCODE){throw 'Packet engine simulation failed'}
 $taskLog=Get-Content -Raw -LiteralPath "$BuildDir\result.log"
 if($taskLog -match 'Fatal:|ERROR:' -or $taskLog -notmatch 'PASS checks=\d+ full_packets=3 sample_cycles=170000 SYMBOL_CYCLES=2500') {
  throw 'Packet engine tests failed; inspect result.log'
 }
 Write-Output "Packet engine simulation passed; log: $BuildDir\result.log"
} finally {Pop-Location}
