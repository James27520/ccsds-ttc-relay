set root [file normalize [file join [file dirname [info script]] ..]]
cd $root
set_param general.maxThreads 4
open_project [file join $root build telecontrol_system.xpr]
if {[get_property PART [current_project]] ne "xc7z020clg484-2"} {error "Wrong physical FPGA part"}
set_property XPM_LIBRARIES {XPM_CDC XPM_MEMORY XPM_FIFO} [current_project]
add_files [glob [file join $root src *.v]]
add_files [glob [file join $root src *.vh]]
add_files [file join $root abi capture_abi.vh]
set_property include_dirs [list [file join $root src] [file join $root abi]] [current_fileset]
add_files -fileset constrs_1 [file join $root constraints pins.xdc]
add_files -fileset constrs_1 [file join $root constraints timing.xdc]
set_property top telecontrol_top [current_fileset]
create_ip -name clk_wiz -vendor xilinx.com -library ip -version 6.0 -module_name clk_wiz_tc
set_property -dict [list CONFIG.PRIM_IN_FREQ {50.000} CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {25.000} CONFIG.CLKOUT2_USED {true} CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {200.000} CONFIG.USE_LOCKED {true} CONFIG.RESET_TYPE {ACTIVE_LOW} CONFIG.RESET_PORT {resetn}] [get_ips clk_wiz_tc]
create_ip -name ila -vendor xilinx.com -library ip -version 6.2 -module_name ila_tc
set_property -dict [list CONFIG.C_NUM_OF_PROBES {4} CONFIG.C_DATA_DEPTH {1024} CONFIG.C_PROBE0_WIDTH {112} CONFIG.C_PROBE1_WIDTH {32} CONFIG.C_PROBE2_WIDTH {8} CONFIG.C_PROBE3_WIDTH {112} CONFIG.C_INPUT_PIPE_STAGES {1} CONFIG.C_ADV_TRIGGER {false}] [get_ips ila_tc]
generate_target all [get_ips {clk_wiz_tc ila_tc}]
update_compile_order -fileset sources_1
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis failed"}
open_run synth_1
set first_sync [get_pins -hier -regexp {.*(clock_done_sync_reg|delay_sync_reg|verified_sync_reg|config_busy_sync_reg|clock_fault_sync_reg|busy_sync_reg|stream_sync_reg|valid_sync_reg|heartbeat_sync_reg)\[0\]/D}]
if {[llength $first_sync] != 9} {error "Expected 9 single-bit first stages; got $first_sync"}
set mailbox_controls [get_pins -hier -regexp {.*[a-z_]*mailbox/(toggle_sync_reg\[0\]|ack_sync_reg\[0\])/D}]
if {[llength $mailbox_controls] != 8} {error "Expected four mailbox toggle/ack first stage pairs; got $mailbox_controls"}
set bundle_first [get_pins -hier -regexp {.*[a-z_]*mailbox/data_meta_reg\[[0-9]+\]/D}]
if {[llength $bundle_first]<100} {error "Missing held-bundle data synchronizers"}
puts "CDC_FIRST_STAGES single=[llength $first_sync] mailbox_controls=[llength $mailbox_controls] bundle_bits=[llength $bundle_first]"
source [file join $root scripts check_mailbox_timing.tcl]
check_mailbox_timing [file join $root reports mailbox_post_synth.txt]
set hub [get_debug_cores -quiet dbg_hub]
if {[llength $hub]} {
 set_property C_CLK_INPUT_FREQ_HZ 25000000 $hub
 connect_debug_port dbg_hub/clk [get_nets clk25]
}
write_checkpoint -force [file join $root reports post_synth.dcp]
# Input XDC is frozen before synthesis. Do not save generated constraints back
# into it; debug-hub properties are already part of the reviewed timing.xdc.
close_design
launch_runs impl_1 -to_step route_design -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation failed"}
open_run impl_1
source [file join $root scripts signoff.tcl]
write_hw_platform -fixed -force -file [file join $root reports telecontrol_system.xsa]
exit
