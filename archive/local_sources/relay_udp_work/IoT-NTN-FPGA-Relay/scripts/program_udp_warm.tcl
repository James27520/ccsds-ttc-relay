# Warm-load only: preserve PS clocks, DDR, MIO and the active PL bitstream.
if {[llength $argv] != 1} { error "usage: program_udp_warm.tcl <elf>" }
connect
puts [targets]
targets -set -filter {name =~ "ARM*#0"}
puts "PS_CLOCK_GATE=[mrd -value 0xF800012C 1]"
puts "GEM_CLOCK=[mrd -value 0xF8000140 1]"
puts "RGMII_MIO=[mrd -value 0xF8000740 12]"
puts "MDIO_MIO=[mrd -value 0xF80007D0 2]"
set clk [mrd -value 0xF800012C 1]
if {($clk & 0x40) == 0} { error "GEM0 clock is disabled; matching PS initialization required" }
stop
dow [lindex $argv 0]
con
puts "UDP_ELF_RUNNING"
disconnect
exit
