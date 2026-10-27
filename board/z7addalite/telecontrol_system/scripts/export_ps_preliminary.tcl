# PS peripheral/BSP preparation only. This XSA has no capture peripheral mapping.
set root [file normalize [file join [file dirname [info script]] ..]]
cd $root
set_param general.maxThreads 4
open_project [file join $root ps_probe telecontrol_ps_probe.xpr]
set bd [get_files -filter {FILE_TYPE == "Block Designs"}]
open_bd_design $bd
make_bd_intf_pins_external [get_bd_intf_pins processing_system7_0/M_AXI_GP0]
set clock [create_bd_port -dir I -type clk clk25]
set_property -dict [list CONFIG.FREQ_HZ 25000000 CONFIG.ASSOCIATED_BUSIF M_AXI_GP0_0] $clock
connect_bd_net $clock [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK]
validate_bd_design
save_bd_design
generate_target all $bd
set wrapper [make_wrapper -files $bd -top]
add_files -norecurse $wrapper
set_property top zynq_petaLinux_wrapper [current_fileset]
update_compile_order -fileset sources_1
write_hw_platform -fixed -force -file [file join $root reports telecontrol_ps_preliminary.xsa]
write_bd_tcl -force [file join $root reports ps_preliminary_export.tcl]
puts "PRELIMINARY_XSA_COMPLETE: PS peripherals only; no capture address map/bitstream"
exit
