#=============================================================================
# run_rx_ideal.ps1 -- validate ccsds_rx_lvds.v alone against an IDEAL stimulus
#
#   powershell -File E:\ccsds_fpga\sim\run_rx_ideal.ps1
#   powershell -File E:\ccsds_fpga\sim\run_rx_ideal.ps1 -Phases 0,1,2,3
#
# Flow:
#   1) python gen_rx_stimulus.py      -> sim\out\rx_stim_i.mem  (ideal samples)
#   2) compile the CCSDS VHDL library + ccsds_rx_lvds.v + tb_ccsds_rx_ideal.v
#   3) sweep PHASE, report PASS/FAIL
#
# WARNING: keep this file PURE ASCII. PowerShell 5.1 reads a BOM-less UTF-8 file
# as ANSI; any non-ASCII character breaks parsing ("Unexpected token ')'").
#=============================================================================

param(
    [string]$Phases = "0,1,2,3,4,5,6,7,8,9"
)
$PhaseArr = @($Phases -split '[,;\s]+' | Where-Object { $_ -ne '' } | ForEach-Object { [int]$_ })
$ErrorActionPreference = 'Stop'

$msim   = 'E:\intelFPGA\18.1\modelsim_ase\win32aloem'
$vlib   = Join-Path $msim 'vlib.exe'
$vcom   = Join-Path $msim 'vcom.exe'
$vlog   = Join-Path $msim 'vlog.exe'
$vsim   = Join-Path $msim 'vsim.exe'

$simDir = 'E:\ccsds_fpga\sim'
$runDir = Join-Path $simDir 'rxideal_run'
$rtlDir = 'E:\ccsds_fpga\rtl\ccsds_rxtx'
$adpDir = 'E:\ccsds_fpga\rtl\adapter'
$py     = 'C:\Users\23638\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# ---- step 1: regenerate the ideal stimulus ----
Write-Host "[1/3] generating ideal stimulus"
& $py (Join-Path $simDir 'gen_rx_stimulus.py') | Out-Null
$mem = Join-Path $simDir 'out\rx_stim_i.mem'
if (-not (Test-Path $mem)) { throw "stimulus not generated: $mem" }
Write-Host ("      {0} bytes" -f (Get-Item $mem).Length)

New-Item -ItemType Directory -Path $runDir -Force | Out-Null
Remove-Item (Join-Path $runDir 'work') -Recurse -Force -ErrorAction SilentlyContinue

# compile order: types/functions must come first
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

    Write-Host "[2/3] compiling"
    $fail = 0
    foreach ($f in $order) {
        $null = & $vcom -quiet -work work (Join-Path $rtlDir $f) 2>&1
        if ($LASTEXITCODE -ne 0) { Write-Host "  VHDL FAIL: $f"; $fail++ }
    }
    if ($fail -gt 0) { throw "$fail VHDL files failed" }

    foreach ($vf in @((Join-Path $adpDir 'ccsds_rx_lvds.v'),
                      (Join-Path $simDir 'bench\tb_ccsds_rx_ideal.v'))) {
        $out = & $vlog -quiet -work work $vf 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  VERILOG FAIL: $vf"
            $out | ForEach-Object { Write-Host "    $_" }
            throw "verilog compile failed"
        }
    }
    Write-Host "      ok"

    Write-Host "[3/3] phase sweep"
    foreach ($ph in $PhaseArr) {
        $garg = "-gPHASE=" + $ph
        $out = & $vsim -c -quiet $garg -do "run -all; quit -f" work.tb_ccsds_rx_ideal 2>&1
        $txt = ($out | Out-String)
        if ($txt -match '\*\*\* PASS \*\*\*') {
            Write-Host ("  PHASE {0,2} : PASS" -f $ph)
            $out | Where-Object { $_ -match 'ASM |err_cnt|crc_ok|crc_calc|解出帧|期望帧|字节不一致|RESULT' } |
                ForEach-Object { Write-Host "        $_" }
        } else {
            $line = ($out | Where-Object { $_ -match 'ASM命中|err_cnt|没有解出' } | Select-Object -First 2) -join ' | '
            Write-Host ("  PHASE {0,2} : fail   {1}" -f $ph, $line.Trim())
        }
    }
}
finally {
    Pop-Location
}
