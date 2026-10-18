#=============================================================================
# run_loopback.ps1 -- CCSDS digital loopback simulation (TX -> RX, same board RTL)
#
#   powershell -File E:\ccsds_fpga\sim\run_loopback.ps1
#   powershell -File E:\ccsds_fpga\sim\run_loopback.ps1 -Phases 0,1,2,3
#
# Sources compiled (the SAME files the board project uses -- no copies allowed):
#   E:\ccsds_fpga\rtl\ccsds_rxtx\*.vhd          CCSDS library (order from run_tx_chain.ps1)
#   E:\ccsds_fpga\rtl\adapter\ccsds_tx_lvds.v   transmitter wrapper
#   E:\ccsds_fpga\rtl\adapter\ccsds_rx_lvds.v   receiver
#   E:\ccsds_fpga\sim\bench\tb_ccsds_loopback.v
#
# WARNING: this file must stay PURE ASCII. PowerShell 5.1 reads a BOM-less
# UTF-8 file as ANSI, so any non-ASCII character here is parsed as garbage and
# the whole script fails with "Unexpected token ')'". Cost an hour once.
#=============================================================================

param(
    [string]$Phases = "0,1,2,3,4,5,6,7,8,9"
)
# powershell -File does NOT parse array arguments: "-Phases 0,1,2" arrives as the
# single string "0,1,2". Split it here (observed: PHASE became 123456789).
$PhaseArr = @($Phases -split '[,;\s]+' | Where-Object { $_ -ne '' } | ForEach-Object { [int]$_ })

$ErrorActionPreference = 'Stop'

$msim   = 'E:\intelFPGA\18.1\modelsim_ase\win32aloem'
$vlib   = Join-Path $msim 'vlib.exe'
$vcom   = Join-Path $msim 'vcom.exe'
$vlog   = Join-Path $msim 'vlog.exe'
$vsim   = Join-Path $msim 'vsim.exe'

$simDir = 'E:\ccsds_fpga\sim'
$runDir = Join-Path $simDir 'loop_run'
$rtlDir = 'E:\ccsds_fpga\rtl\ccsds_rxtx'
$adpDir = 'E:\ccsds_fpga\rtl\adapter'

New-Item -ItemType Directory -Path $runDir -Force | Out-Null
Remove-Item (Join-Path $runDir 'work') -Recurse -Force -ErrorAction SilentlyContinue

# compile order: types/functions must come first (the upstream .core file has it wrong)
$order = @(
  'ccsds_rxtx_constants.vhd'
  'ccsds_rxtx_types.vhd'
  'ccsds_rxtx_functions.vhd'
  'ccsds_rxtx_parameters.vhd'
  'ccsds_rx.vhd'
  'ccsds_rxtx_buffer.vhd'
  'ccsds_rxtx_clock_divider.vhd'
  'ccsds_rxtx_crc.vhd'
  'ccsds_rxtx_lfsr.vhd'
  'ccsds_rxtx_oversampler.vhd'
  'ccsds_rxtx_serdes.vhd'
  'ccsds_rxtx_srrc.vhd'
  'ccsds_rxtx_top.vhd'
  'ccsds_rx_datalink_layer.vhd'
  'ccsds_rx_physical_layer.vhd'
  'ccsds_tx.vhd'
  'ccsds_tx_coder.vhd'
  'ccsds_tx_coder_convolutional.vhd'
  'ccsds_tx_coder_differential.vhd'
  'ccsds_tx_datalink_layer.vhd'
  'ccsds_tx_filter.vhd'
  'ccsds_tx_footer.vhd'
  'ccsds_tx_framer.vhd'
  'ccsds_tx_header.vhd'
  'ccsds_tx_manager.vhd'
  'ccsds_tx_mapper_bits_symbols.vhd'
  'ccsds_tx_mapper_symbols_samples.vhd'
  'ccsds_tx_physical_layer.vhd'
  'ccsds_tx_randomizer.vhd'
  'ccsds_tx_synchronizer.vhd'
)

Push-Location $runDir
try {
    & $vlib work | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "vlib failed" }

    $fail = 0
    foreach ($f in $order) {
        $null = & $vcom -quiet -work work (Join-Path $rtlDir $f) 2>&1
        if ($LASTEXITCODE -ne 0) { Write-Host "VHDL COMPILE FAIL: $f"; $fail++ }
    }
    if ($fail -gt 0) { throw "$fail VHDL files failed" }
    Write-Host "[ok] VHDL library compiled: $($order.Count)/$($order.Count)"

    $vfiles = @(
        (Join-Path $adpDir 'ccsds_tx_lvds.v'),
        (Join-Path $adpDir 'ccsds_rx_lvds.v'),
        (Join-Path $simDir 'bench\tb_ccsds_loopback.v')
    )
    foreach ($vf in $vfiles) {
        $out = & $vlog -quiet -work work $vf 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "VERILOG COMPILE FAIL: $vf"
            $out | ForEach-Object { Write-Host "    $_" }
            throw "verilog compile failed"
        }
    }
    Write-Host "[ok] Verilog DUT + testbench compiled"

    Write-Host ""
    Write-Host "=================== PHASE SWEEP ==================="
    foreach ($ph in $PhaseArr) {
        $garg = "-gPHASE=" + $ph
        $out = & $vsim -c -quiet $garg -do "run -all; quit -f" work.tb_ccsds_loopback 2>&1
        $txt = ($out | Out-String)
        $pass = if ($txt -match '\*\*\* PASS \*\*\*') { 'PASS' } else { 'fail' }
        $line = ($out | Where-Object { $_ -match 'frame mismatches|byte mismatches|frames=' } | Select-Object -First 2) -join ' | '
        Write-Host ("  PHASE {0,2} : {1}   {2}" -f $ph, $pass, $line.Trim())
        if ($pass -eq 'PASS') {
            $out | Where-Object { $_ -match 'RESULT|crc_ok|crc_calc|crc_rx|err_cnt|decoded frame|expected frame|^    [0-9a-f]' } |
                ForEach-Object { Write-Host "        $_" }
        }
    }
    Write-Host "==================================================="
}
finally {
    Pop-Location
}
