#=============================================================================
# program_device.tcl -- XSCT: load the bitstream and run the bare-metal app
#
#   xsct.bat E:/LDSDR_010/program_device.tcl
#
# Zynq-7000 JTAG flow
#   1. connect to hw_server / the Digilent cable
#   2. reset the whole system (PS + PL)
#   3. ps7_init  -- brings up the PS PLLs, MIO and, crucially, the DDR
#                   controller.  Without it "dow" fails with
#                   "Cannot access DDR: the controller is held in reset".
#   4. program the PL with the relay bitstream
#   5. ps7_post_config -- enable the PS/PL level shifters
#   6. download 9361.elf to DDR and start it
#
# After this the PL relays on its own.  Open the PS UART (115200 8N1) to see
# the banner printed by main.c.
#=============================================================================

set BIT    "E:/LDSDR_010/zynq_dev_fmcomms3.runs/impl_2/ad9361_top.bit"
set ELF    "E:/LDSDR_010/zynq_dev_fmcomms3.sdk/9361/Debug/9361.elf"
set PS7INI "E:/LDSDR_010/zynq_dev_fmcomms3.sdk/ad9361_top_hw_platform_0/ps7_init.tcl"

proc banner {m} { puts "\n========== $m ==========" }

banner "0. check files"
foreach f [list $BIT $ELF $PS7INI] {
    if {![file exists $f]} { error "missing: $f" }
    puts "  [file tail $f] : [file size $f] bytes"
}

banner "1. connect"
connect
puts [targets]

banner "2. reset system"
targets -set -filter {name =~ "APU*"}
catch {rst -system}
after 3000

banner "3. PS7 init (clocks, MIO, DDR)"
targets -set -filter {name =~ "ARM*#0"}
source $PS7INI
if {[catch {ps7_init} e]} { error "ps7_init failed: $e" }
puts "  ps7_init OK"

banner "4. program PL"
fpga -file $BIT
puts "  PL programmed"

banner "5. PS/PL level shifters"
catch {ps7_post_config}
puts "  ps7_post_config done"

banner "6. download and run application"
dow $ELF
after 500
con
puts "  application started"

banner "7. target state"
after 2000
puts [targets]
puts "\nOpen the PS UART at 115200 8N1.  main.c prints:"
puts "  ===== PL relay enabled ====="
puts "    RX_LO / TX_LO / sample_rate / TX atten / relay mode"
puts "    status : in=<n> out=<n> clip=<n> rc=<n>"
puts ""
puts "rc =  0 : relay healthy (ADC samples are flowing out to the DAC)"
puts "rc = -1 : no ADC data  - check the AD9361 RX input and PHY mode"
puts "rc = -2 : ADC running but no DAC output"
puts ""
puts "If it prints rc != 0 the relay muted itself (safe state)."
