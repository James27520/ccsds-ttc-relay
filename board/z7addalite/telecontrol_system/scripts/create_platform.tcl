set root [file normalize [file join [file dirname [info script]] ..]]
cd $root
set_param general.maxThreads 4
create_project -force telecontrol_system [file join $root build] -part xc7z020clg484-2
set_property target_language Verilog [current_project]
import_files -norecurse [file join $root vendor zynq_petaLinux.bd]
set bd [get_files -filter {FILE_TYPE == "Block Designs"}]
open_bd_design $bd
set ps [get_bd_cells processing_system7_0]
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 {1} CONFIG.PCW_EN_RST0_PORT {1}] $ps
set sc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_router]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {2} CONFIG.NUM_CLKS {1}] $sc
set clk [create_bd_port -dir I -type clk -freq_hz 25000000 clk25]
set rst [create_bd_port -dir I -type rst axi_resetn]
set_property CONFIG.POLARITY ACTIVE_LOW $rst
connect_bd_net $clk [get_bd_pins $ps/M_AXI_GP0_ACLK] [get_bd_pins $sc/aclk]
connect_bd_net $rst [get_bd_pins $sc/aresetn]
connect_bd_intf_net [get_bd_intf_pins $ps/M_AXI_GP0] [get_bd_intf_pins $sc/S00_AXI]
foreach {port pin} {M_AXI_CTRL M00_AXI M_AXI_RAM M01_AXI} {
 set p [create_bd_intf_port -mode Master -vlnv xilinx.com:interface:aximm_rtl:1.0 $port]
 set_property -dict [list CONFIG.PROTOCOL AXI4LITE CONFIG.DATA_WIDTH 32 CONFIG.ADDR_WIDTH 32 CONFIG.FREQ_HZ 25000000 CONFIG.HAS_BURST 0 CONFIG.HAS_LOCK 0 CONFIG.HAS_CACHE 0 CONFIG.HAS_QOS 0 CONFIG.HAS_REGION 0] $p
 connect_bd_intf_net $p [get_bd_intf_pins $sc/$pin]
}
set_property -dict [list CONFIG.ASSOCIATED_RESET axi_resetn CONFIG.ASSOCIATED_BUSIF {M_AXI_CTRL:M_AXI_RAM}] $clk
make_bd_pins_external [get_bd_pins $ps/FCLK_RESET0_N]
set_property name ps_resetn [get_bd_ports FCLK_RESET0_N_0]
assign_bd_address -offset 0x43C00000 -range 64K -target_address_space [get_bd_addr_spaces $ps/Data] [get_bd_addr_segs M_AXI_CTRL/Reg] -force
assign_bd_address -offset 0x44000000 -range 256K -target_address_space [get_bd_addr_spaces $ps/Data] [get_bd_addr_segs M_AXI_RAM/Reg] -force
validate_bd_design
save_bd_design
set fp [open [file join $root reports platform_addresses.txt] w]
foreach seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces $ps/Data]] {
 puts $fp "$seg OFFSET=[get_property OFFSET $seg] RANGE=[get_property RANGE $seg]"
}
close $fp
set fp [open [file join $root reports platform_ps_properties.txt] w]
foreach p [lsort [list_property $ps]] {
 if {[string match CONFIG.PCW* $p]} {puts $fp "$p=[get_property $p $ps]"}
}
close $fp
generate_target all $bd
set wrapper [make_wrapper -files $bd -top]
add_files -norecurse $wrapper
set_property top zynq_petaLinux_wrapper [current_fileset]
update_compile_order -fileset sources_1
write_hw_platform -fixed -force -file [file join $root reports telecontrol_platform.xsa]
write_bd_tcl -force [file join $root reports platform_export.tcl]
puts "PLATFORM_BD_COMPLETE: assigned AXI boundaries; custom slaves pending implementation"
exit
