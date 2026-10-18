#=============================================================================
# verify_standard_randomizer.ps1
#
# One-shot regression for the CCSDS-standard randomiser.
#
#   powershell -File E:\ccsds_fpga\sim\verify_standard_randomizer.ps1
#
# NOTE: this script is deliberately pure ASCII.  PowerShell 5.1 reads a
# UTF-8 file WITHOUT a BOM as ANSI, which corrupts any non-ASCII string
# literal and breaks parsing.  Keep it ASCII.
#
# Checks (all must PASS):
#   1. Python rand_seq hits the standard sequence (FF 48 0E C0 9A 0D), period 255
#   2. VHDL simulation (tb_lfsr) exports a sequence
#   3. VHDL sequence == Python sequence, bit for bit (160 bit)
#   4. Coder chain (randomiser -> conv -> ASM) == Python, bit for bit (672 bit CADU)
#   5. Full-chain CADU decodes in the verified Python ground receiver
#      (CRC OK + payload byte-exact)
#
# Background: CCSDS 131.0-B uses h(x)=x^8+x^7+x^5+x^3+1, written mathematically
# as 0xA9.  This RTL is a LEFT-shifting register emitting bit7, so it must be
# fed the BIT-REVERSED mask 0x95.  Using 0xA9 yields the wrong 217-period
# sequence (AD 75 59 34 CD C4) and no receiver can de-randomise it.
#=============================================================================

$ErrorActionPreference = 'Continue'
$py  = 'C:\Users\23638\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$sim = 'E:\ccsds_fpga\sim'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$script:fail = 0
function Section($t) { Write-Host ""; Write-Host "========== $t ==========" -ForegroundColor Cyan }
function Pass($t)    { Write-Host "  [PASS] $t" -ForegroundColor Green }
function Fail($t)    { Write-Host "  [FAIL] $t" -ForegroundColor Red; $script:fail++ }

Section '1. Python reference randomiser sequence'
$r = & $py "$sim\check_lfsr_standard.py" 2>&1 | Out-String
Write-Host $r.TrimEnd()
if ($r -match 'RESULT: PASS') { Pass 'Python sequence is the CCSDS standard' } else { Fail 'Python sequence check failed' }

Section '2. VHDL simulation (tb_lfsr)'
& powershell -File "$sim\run_sim.ps1" -Tb tb_lfsr 2>&1 |
  Select-String -Pattern 'Errors:|COMPILE FAIL|never became valid' | ForEach-Object { "  $($_.Line.Trim())" }
if (Test-Path "$sim\out\lfsr_bits.txt") { Pass 'tb_lfsr exported lfsr_bits.txt' } else { Fail 'tb_lfsr produced no data' }

Section '3. VHDL vs Python, bit for bit (160 bit)'
$r = & $py "$sim\check_lfsr_vhdl.py" 2>&1 | Out-String
Write-Host $r.TrimEnd()
if ($r -match 'RESULT: PASS') { Pass 'LFSR sequences identical' } else { Fail 'LFSR sequences differ' }

Section '4. Coder chain bit-exact (tb_coder_only, 672 bit CADU)'
& powershell -File "$sim\run_sim.ps1" -Tb tb_coder_only 2>&1 |
  Select-String -Pattern 'Errors:|COMPILE FAIL' | ForEach-Object { "  $($_.Line.Trim())" }
$r = & $py "$sim\check_coder_only.py" 2>&1 | Out-String
Write-Host $r.TrimEnd()
if ($r -match 'IDENTICAL') { Pass 'coder chain identical' } else { Fail 'coder chain differs' }

Section '5. End to end (tb_ccsds_tx_chain -> verified Python ground receiver)'
& powershell -File "$sim\run_sim.ps1" -Tb tb_ccsds_tx_chain 2>&1 |
  Select-String -Pattern 'Errors:|COMPILE FAIL' | ForEach-Object { "  $($_.Line.Trim())" }
$r = & $py "$sim\check_tx_chain.py" 2>&1 | Out-String
Write-Host $r.TrimEnd()
if ($r -match 'RESULT: PASS') { Pass 'end-to-end PASS (CRC OK, payload byte-exact)' } else { Fail 'end-to-end failed' }

Section '6. Dynamic frame source (tb_frame_gen2 -> build_tm_frame)'
& powershell -File "$sim\run_sim.ps1" -Tb tb_frame_gen2 2>&1 |
  Select-String -Pattern 'Errors:|COMPILE FAIL' | ForEach-Object { "  $($_.Line.Trim())" }
$r = & $py "$sim\check_frame_gen.py" 2>&1 | Out-String
Write-Host $r.TrimEnd()
if ($r -match 'RESULT: PASS') { Pass 'frame_gen assembly byte-exact vs build_tm_frame (incl. FECF)' } else { Fail 'frame_gen mismatch' }

Section 'RESULT'
if ($script:fail -eq 0) {
  Write-Host '  ALL PASS - randomiser is CCSDS 131.0-B standard, Python and FPGA agree.' -ForegroundColor Green
  exit 0
} else {
  Write-Host ("  " + $script:fail + " check(s) FAILED.") -ForegroundColor Red
  exit 1
}
