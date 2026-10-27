# Run only after the routed reports and frozen manifest have been reviewed.
if {$argc != 1 || [lindex $argv 0] ne "reviewed"} {error "Explicit routed review acknowledgement required"}
set root [file normalize [file join [file dirname [info script]] ..]]
cd $root
set f [open [file join $root reports signoff.txt] r];set signoff [read $f];close $f
if {![regexp {STA_PASS=1\s} $signoff]} {error "Missing successful routed signoff"}
open_project [file join $root build telecontrol_system.xpr]
if {[get_property PART [current_project]] ne "xc7z020clg484-2"} {error "Wrong physical FPGA part"}
open_run impl_1
source [file join $root scripts check_mailbox_timing.tcl]
check_mailbox_timing [file join $root reports mailbox_pre_bitstream.txt]
set run_bit [file join [get_property DIRECTORY [get_runs impl_1]] telecontrol_top.bit]
write_bitstream -force $run_bit
file copy -force $run_bit [file join $root artifacts telecontrol_system.bit]
write_debug_probes -force [file join $root artifacts telecontrol_system.ltx]
write_hw_platform -fixed -include_bit -force -file [file join $root artifacts telecontrol_system_final.xsa]
puts "REVIEWED_BITSTREAM_AND_XSA_EXPORTED=1"
exit
