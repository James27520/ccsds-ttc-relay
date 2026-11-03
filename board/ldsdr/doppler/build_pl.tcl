# vivado -mode batch -source build_pl.tcl -tclargs <baseline.xpr> <NEW out>
# Never touches hardware. Save as a new project before making any changes.
if {$argc != 2} {error "baseline XPR and new output directory required"}
set base [file normalize [lindex $argv 0]]
set work [file normalize [lindex $argv 1]]
set here [file dirname [file normalize [info script]]]
if {[file exists $work]} {error "output must not exist"}
open_project $base
if {[get_property PART [current_project]] ne "xc7z010clg400-1"} {error "wrong device"}
save_project_as doppler_business $work
# Own a copy of the custom IP repositories, so generation cannot alter inputs.
file copy [file join [file dirname $base] repo] [file join $work repo]
set_property ip_repo_paths [list [file join $work repo]] [current_project]
update_ip_catalog -rebuild
file mkdir $work/doppler_src
file copy $here/relay_iq_snapshot.v $work/doppler_src/relay_iq_snapshot.v
add_files -norecurse $work/doppler_src/relay_iq_snapshot.v
update_compile_order -fileset sources_1
set bdf [get_files design_1.bd]
open_bd_design $bdf
create_bd_cell -type module -reference relay_iq_snapshot doppler_iq
set_property CONFIG.NUM_MI {2} [get_bd_cells axi_interconnect_0]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect_0/M01_AXI] [get_bd_intf_pins doppler_iq/s_axi]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins doppler_iq/s_axi_aclk] [get_bd_pins axi_interconnect_0/M01_ACLK]
connect_bd_net [get_bd_pins proc_sys_reset_0/peripheral_aresetn] [get_bd_pins doppler_iq/s_axi_aresetn] [get_bd_pins axi_interconnect_0/M01_ARESETN]
foreach {src dst} {data_clk dq_clk adc_d1q1_valid valid1 adc_d2q2_valid valid2 adc_data_d1 i1 adc_data_q1 q1 adc_data_d2 i2 adc_data_q2 q2} {
    connect_bd_net [get_bd_pins ad9361_phy_0/$src] [get_bd_pins doppler_iq/$dst]
}
assign_bd_address -offset 0x43C10000 -range 64K -target_address_space [get_bd_addr_spaces processing_system7_0/Data] [get_bd_addr_segs doppler_iq/s_axi/reg0] -force
validate_bd_design
save_bd_design
write_bd_tcl -force $work/design.tcl
generate_target all $bdf
update_compile_order -fileset sources_1
set syn [current_run -synthesis]
set imp [current_run -implementation]
if {[llength $syn]!=1 || [llength $imp]!=1} {error "ambiguous build runs: $syn $imp"}
reset_run $syn
launch_runs $syn -jobs 4
wait_on_run $syn
if {[get_property PROGRESS $syn] ne "100%"} {error "synthesis failed"}
launch_runs $imp -to_step write_bitstream -jobs 4
wait_on_run $imp
if {[get_property PROGRESS $imp] ne "100%"} {error "implementation failed"}
open_run $imp
report_timing_summary -delay_type min_max -report_unconstrained -file $work/timing.txt
report_utilization -file $work/utilization.txt
report_drc -file $work/drc.txt
report_cdc -file $work/cdc.txt
set wns [get_property SLACK [get_timing_paths -delay_type max]]
set whs [get_property SLACK [get_timing_paths -delay_type min]]
puts "DOPPLER_PL_TIMING WNS=$wns WHS=$whs"
if {$wns<0 || $whs<0} {error "timing not met"}
puts "DOPPLER_PL_PASS"
close_project
