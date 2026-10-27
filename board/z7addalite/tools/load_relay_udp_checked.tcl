# Volatile LDSDR DDR load. Preserve the already initialized PS and PL.
if {[llength $argv] != 2} {error "usage: load_relay_udp_checked.tcl <ELF> <LDSDR cable serial>"}
set image [file normalize [lindex $argv 0]]
set serial [lindex $argv 1]
if {![file exists $image] || ![regexp {^[A-Za-z0-9]+$} $serial]} {error "Invalid ELF or cable serial"}
connect -url tcp:127.0.0.1:3121
set cpu [targets -target-properties -filter "name =~ \"ARM*#0\" && jtag_cable_serial == \"$serial\""]
set fpga [targets -target-properties -filter "name == \"xc7z010\" && jtag_cable_serial == \"$serial\""]
if {[llength $cpu] != 1 || [llength $fpga] != 1} {error "Expected exact LDSDR XC7Z010 and Cortex-A9 core0"}
targets -set [dict get [lindex $cpu 0] target_id]
set clk [mrd -value 0xF800012C 1]
puts "PS_CLOCK_GATE=$clk GEM_CLOCK=[mrd -value 0xF8000140 1]"
puts "RGMII_MIO=[mrd -value 0xF8000740 12] MDIO_MIO=[mrd -value 0xF80007D0 2]"
if {($clk & 0x40) == 0} {error "GEM0 clock disabled; matching LDSDR PS initialization required"}
set stage stop
set failed [catch {
    if {[catch {stop} reason] && ![string match "*Already stopped*" $reason]} {error $reason}
    set stage download
    dow $image
    set stage resume
    con
} reason]
if {$failed} {
    catch {disconnect}
    error "LDSDR load failed at $stage: $reason. CPU may be stopped and DDR image incomplete; no automatic resume attempted."
}
puts "LDSDR_UDP_RUNNING cable=$serial ELF=$image"
disconnect
exit
