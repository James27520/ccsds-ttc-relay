#=============================================================================
# run_sim.ps1 -- compile the patched protocol core and run one testbench
#
#   powershell -File E:\ccsds_fpga\sim\run_sim.ps1 -Tb tb_framer_coder [-Lib libname]
#
# Output is streamed to a transcript file rather than buffered, so a long
# simulation can be watched while it runs.
#=============================================================================

param(
  [Parameter(Mandatory = $true)][string]$Tb,
  [string]$Lib = 'work'
)

$ErrorActionPreference = 'Stop'

$msim   = 'E:\intelFPGA\18.1\modelsim_ase\win32aloem'
$vlib   = Join-Path $msim 'vlib.exe'
$vcom   = Join-Path $msim 'vcom.exe'
$vsim   = Join-Path $msim 'vsim.exe'

$simDir = 'E:\ccsds_fpga\sim'
$runDir = Join-Path $simDir 'tx_run'
$rtlDir = 'E:\ccsds_fpga\rtl\ccsds_rxtx'
$outDir = Join-Path $simDir 'out'

New-Item -ItemType Directory -Path $runDir -Force | Out-Null
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
Remove-Item (Join-Path $runDir 'work') -Recurse -Force -ErrorAction SilentlyContinue

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
  'frame_gen.vhd'
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
    $src = Join-Path $rtlDir $f
    $o = & $vcom -quiet -work work $src 2>&1
    if ($LASTEXITCODE -ne 0) {
      Write-Host "COMPILE FAIL: $f" -ForegroundColor Red
      $o | ForEach-Object { Write-Host "    $_" }
      $fail++
    }
  }
  if ($fail -gt 0) { throw "$fail core files failed to compile" }
  Write-Host "core compiled: $($order.Count)/$($order.Count) OK" -ForegroundColor Green

  $tbf = Join-Path $simDir "bench\$Tb.vhd"
  $o = & $vcom -quiet -work work $tbf 2>&1
  if ($LASTEXITCODE -ne 0) {
    Write-Host "COMPILE FAIL: $Tb" -ForegroundColor Red
    $o | ForEach-Object { Write-Host "    $_" }
    throw "testbench failed to compile"
  }
  Write-Host "testbench compiled OK" -ForegroundColor Green

  & $vsim -c -do "run -all; quit -f" "work.$Tb"
  Write-Host "vsim exit: $LASTEXITCODE"
}
finally {
  Pop-Location
}
