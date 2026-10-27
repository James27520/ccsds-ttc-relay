# Volatile DDR application load; requires the matching reviewed ADDA PS init.
# No flash/SD writes. The caller must have checked the PL and XSA build IDs.
if {[llength $argv] != 4} {error "usage: load_telecontrol_ps.tcl <ELF> <ps7_init.tcl> <matching BIT> <cable-serial>"}
set image [file normalize [lindex $argv 0]]
set init [file normalize [lindex $argv 1]]
set bit [file normalize [lindex $argv 2]]
if {![file exists $image] || ![file exists $init] || ![file exists $bit]} {error "Missing reviewed ELF, BIT or ADDA PS init"}
set serial [lindex $argv 3]
if {![regexp {^[A-Za-z0-9]+$} $serial]} {error "Invalid cable serial"}
connect -url tcp:127.0.0.1:3121
proc stop_checked {} {
 if {[catch {stop} reason] && ![string match "*Already stopped*" $reason]} {error $reason}
}
set candidates [targets -target-properties -filter "name =~ \"ARM*#0\" && jtag_cable_serial == \"$serial\""]
set secondary [targets -target-properties -filter "name =~ \"ARM*#1\" && jtag_cable_serial == \"$serial\""]
set fpga [targets -target-properties -filter "name == \"xc7z020\" && jtag_cable_serial == \"$serial\""]
if {[llength $candidates] != 1 || [llength $secondary] != 1 || [llength $fpga] != 1} {
 error "Expected exact ADDA cable, XC7Z020, and both Cortex-A9 cores"
}
# Reset the PS and its old peripherals, not only one CPU's execution state.
targets -set [dict get [lindex $candidates 0] target_id]
rst -system -stop
after 1000
# Re-resolve core handles after reset and stop both before shared DDR setup.
set candidates [targets -target-properties -filter "name =~ \"ARM*#0\" && jtag_cable_serial == \"$serial\""]
set secondary [targets -target-properties -filter "name =~ \"ARM*#1\" && jtag_cable_serial == \"$serial\""]
if {[llength $candidates] != 1 || [llength $secondary] != 1} {error "Lost exact ADDA cores after reset"}
targets -set [dict get [lindex $secondary 0] target_id]
stop_checked
targets -set [dict get [lindex $candidates 0] target_id]
stop_checked
set fpga [targets -target-properties -filter "name == \"xc7z020\" && jtag_cable_serial == \"$serial\""]
if {[llength $fpga] != 1} {error "Lost exact ADDA FPGA after reset"}
targets -set [dict get [lindex $fpga 0] target_id]
fpga -file $bit
targets -set [dict get [lindex $candidates 0] target_id]
source $init
ps7_init
ps7_post_config
puts "ADDA_PS_INIT_COMPLETE"
dow $image
con
puts "TELECONTROL_PS_RUNNING cable=$serial ELF=$image"
disconnect
exit
