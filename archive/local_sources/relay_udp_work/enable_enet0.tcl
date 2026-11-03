# Vivado 2018.3: vivado -mode batch -source enable_enet0.tcl -tclargs <copied .xpr>
if {[llength $argv] != 1} { error "usage: enable_enet0.tcl <copied .xpr>" }
open_project [lindex $argv 0]
set bd [get_files -all -filter {NAME =~ *design_1.bd}]
if {[llength $bd] != 1} { error "expected one design_1.bd" }
open_bd_design $bd
set ps [get_bd_cells processing_system7_0]
if {[llength $ps] != 1} { error "processing_system7_0 not found" }
set_property -dict [list \
    CONFIG.PCW_ENET0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_ENET0_GRP_MDIO_ENABLE {1} \
    CONFIG.PCW_ENET0_ENET0_IO {MIO 16 .. 27} \
    CONFIG.PCW_ENET0_GRP_MDIO_IO {MIO 52 .. 53}] $ps
validate_bd_design
save_bd_design
generate_target all $bd
puts "ENET0/MDIO enabled. Rebuild bitstream, export new HDF, regenerate BSP."
close_project
