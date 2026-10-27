set root [file normalize [file join [file dirname [info script]] ..]]
cd $root
set_param general.maxThreads 4
create_project -force telecontrol_ps_probe [file join $root ps_probe] -part xc7z020clg484-2
set_property target_language Verilog [current_project]
# Import a task-owned copy; never edit the vendor archive or M1 snapshot.
import_files -norecurse [file join $root vendor zynq_petaLinux.bd]
set bd [get_files -filter {FILE_TYPE == "Block Designs"}]
open_bd_design $bd
set ip [get_ips -all]
if {[llength $ip]} {upgrade_ip $ip}
set ps [get_bd_cells processing_system7_0]
set_property CONFIG.PCW_USE_M_AXI_GP0 1 $ps
set fp [open [file join $root reports ps_baseline_properties.txt] w]
foreach p [lsort [list_property $ps]] {
 if {[string match CONFIG.PCW* $p]} {puts $fp "$p=[get_property $p $ps]"}
}
close $fp
report_ip_status -file [file join $root reports ps_ip_status.txt]
write_bd_tcl -force [file join $root reports ps_baseline_export.tcl]
save_bd_design
puts "PS_PROBE_COMPLETE: not synthesized, no bitstream, no hardware access"
exit
