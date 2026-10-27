# Offline BSP-generation entry point. Supply the final ADDA XSA and a reviewed
# MSS whose processor/peripheral instances and driver versions match that XSA.
# The proven UART-only vendor MSS is NOT suitable for M2 Ethernet hardware.
# Usage: xsdb.bat generate_m2_bsp_template.tcl final_adda.xsa reviewed_m2.mss new_output_dir
# Does not connect to a target, initialize DDR, or download any software.
if {$argc != 3} {error "Require: final ADDA XSA, reviewed M2 MSS, new output directory"}
set base [file dirname [file normalize [info script]]]
set xsa [file normalize [lindex $argv 0]]
set mss [file normalize [lindex $argv 1]]
set out [file normalize [lindex $argv 2]]
if {[string tolower [file extension $xsa]] ne ".xsa" || ![file isfile $xsa]} {error "Final .xsa required"}
if {![file isfile $mss]} {error "Reviewed matching MSS required"}
if {[file exists $out]} {error "Refuse to overwrite $out"}
hsi set_repo_path [file join $base embeddedsw_2018_subset]
set hw [hsi open_hw_design $xsa -outdir [file join $out xsa_extracted]]
if {[llength [hsi get_cells ps7_cortexa9_0]] != 1} {error "Expected ADDA A9 core0 missing"}
if {[llength [hsi get_cells ps7_uart_1]] != 1} {error "ADDA UART1 missing; check XSA/MSS"}
if {[llength [hsi get_cells -filter {IP_NAME == ps7_ethernet}]] == 0} {error "Ethernet PS peripheral absent; do not reuse UART-only hardware"}
puts "HARDWARE=$hw"
puts "PROCESSORS=[hsi get_cells -filter {IP_TYPE == PROCESSOR}]"
puts "MSS=$mss"
hsi generate_bsp -hw $hw -sw_mss $mss -dir $out
puts "BSP_GENERATED=$out"
hsi close_hw_design $hw
exit
