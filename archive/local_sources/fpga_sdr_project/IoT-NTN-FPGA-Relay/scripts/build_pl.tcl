#=============================================================================
# build_pl.tcl -- batch build of the relay-enabled bitstream
#
#   vivado.bat -mode batch -source E:/LDSDR_010/build_pl.tcl ^
#              -log E:/LDSDR_010/build_pl.log -journal E:/LDSDR_010/build_pl.jou
#
# Order matters:
#   1. update the IP catalog so the patched repo/axi_ctrl/component.xml is read
#   2. modify the block design (insert relay_dq, rewire the DAC port)
#   3. RESET + REGENERATE the block design - this recreates the nested
#      axi_ctrl IP from repo/ and is the only way to refresh a nested
#      sub-design (resetting the nested IP directly is refused by Vivado)
#   4. verify that the new ports really appeared before spending time on
#      synthesis
#   5. synthesize, implement, write the bitstream
#=============================================================================

set PROJ   "E:/LDSDR_010/zynq_dev_fmcomms3.xpr"
set SYNTH  "synth_2"
set IMPL   "impl_2"

proc banner {msg} { puts "\n========== $msg ==========" }

banner "1. open project"
open_project $PROJ
puts "project : [current_project]"
puts "part    : [get_property PART [current_project]]"
puts "top     : [get_property TOP [get_filesets sources_1]]"

banner "2. rebuild IP catalog"
update_ip_catalog -rebuild

banner "3. refresh the nested axi_ctrl IP BEFORE touching the block design"
# The BD cell's port list comes from the generated IP products, not from the
# .bd file.  Resetting + regenerating the BD recreates design_1_axi_ctrl_v1_0_0_1
# from repo/axi_ctrl, so the 8 new ports only exist after this step.  Doing it
# before modify_bd.tcl is what makes tie_or_connect see them.
set bdf [get_files -quiet design_1.bd]
if {$bdf eq ""} { error "design_1.bd not found" }
reset_target    all $bdf
generate_target all $bdf
puts "BD output products regenerated"

banner "4. apply the block design modification"
source E:/LDSDR_010/modify_bd.tcl

banner "5. regenerate the block design after the edit"
generate_target all $bdf
puts "BD regenerated"

banner "6. verify the axi_ctrl patch propagated"
set found 0
foreach f [list \
    "E:/LDSDR_010/zynq_dev_fmcomms3.srcs/sources_1/bd/design_1/ipshared/6d2a/axi_ctrl_v1_0.v" \
    "E:/LDSDR_010/zynq_dev_fmcomms3.srcs/sources_1/bd/design_1/ipshared/6d2a/axi_ctrl_v1_0_S00_AXI.v" ] {
    if {[file exists $f]} {
        set fh [open $f r]; set data [read $fh]; close $fh
        set ok [string match "*relay_ddc_freq*" $data]
        puts "  [file tail $f] : relay_ddc_freq present = $ok"
        if {$ok} { incr found }
    } else {
        puts "  MISSING: $f"
    }
}
if {$found < 2} {
    puts "\n!! the patched axi_ctrl IP did NOT propagate."
    puts "!! modify_bd.tcl has already tied the relay control ports to"
    puts "!! xlconstant defaults, so the build can still continue as a plain"
    puts "!! 1:1 bent pipe.  Stopping here so it can be investigated."
    puts "!! Inspect with:  get_bd_cells relay_dq_0 ; report_property [get_bd_cells relay_dq_0]"
    error "axi_ctrl patch not propagated"
}
puts "  --> axi_ctrl patch verified"

banner "7. synthesis"
reset_run $SYNTH
launch_runs $SYNTH -jobs 4
wait_on_run $SYNTH
if {[get_property PROGRESS [get_runs $SYNTH]] != "100%"} {
    error "SYNTHESIS FAILED: [get_property STATUS [get_runs $SYNTH]]"
}
puts "synthesis OK : [get_property STATUS [get_runs $SYNTH]]"

banner "8. implementation + bitstream"
launch_runs $IMPL -to_step write_bitstream -jobs 4
wait_on_run $IMPL
if {[get_property PROGRESS [get_runs $IMPL]] != "100%"} {
    error "IMPLEMENTATION FAILED: [get_property STATUS [get_runs $IMPL]]"
}
puts "implementation OK : [get_property STATUS [get_runs $IMPL]]"

banner "9. results"
open_run $IMPL

puts "\n---- utilization ----"
foreach line [split [report_utilization -return_string] "\n"] {
    if {[string match "*Slice LUTs*"          $line] ||
        [string match "*Slice Registers*"     $line] ||
        [string match "*Block RAM Tile*"      $line] ||
        [string match "*DSPs*"                $line] ||
        [string match "*Bonded IOB*"          $line] ||
        [string match "*BUFGCTRL*"            $line] ||
        [string match "*LUT as Memory*"       $line]} {
        puts "  $line"
    }
}

puts "\n---- timing ----"
set wns [get_property SLACK [get_timing_paths -delay_type max]]
set whs [get_property SLACK [get_timing_paths -delay_type min]]
puts "  WNS (setup) = $wns ns"
puts "  WHS (hold)  = $whs ns"
if {$wns < 0} { puts "  !! SETUP TIMING NOT MET - bitstream is not reliable" }

puts "\n---- bitstream ----"
set rdir [get_property DIRECTORY [get_runs $IMPL]]
set top  [get_property TOP [current_fileset]]
set bit  "$rdir/$top.bit"
puts "  expected : $bit"
if {[file exists $bit]} {
    puts "  FOUND    : [file size $bit] bytes"
} else {
    foreach f [glob -nocomplain "$rdir/*.bit"] {
        puts "  candidate: $f ([file size $f] bytes)"
    }
}

banner "BUILD DONE"
