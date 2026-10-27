set reports [file join $root reports]
source [file join $root scripts check_mailbox_timing.tcl]
check_mailbox_timing [file join $reports mailbox_routed.txt]
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -file [file join $reports timing_summary.rpt]
check_timing -verbose -file [file join $reports check_timing.rpt]
report_clocks -file [file join $reports clocks.rpt]
report_bus_skew -file [file join $reports bus_skew.rpt]
report_route_status -file [file join $reports route_status.rpt]
report_clock_interaction -file [file join $reports clock_interaction.rpt]
report_cdc -details -file [file join $reports cdc.rpt]
report_exceptions -file [file join $reports exceptions.rpt]
report_exceptions -ignored -file [file join $reports ignored_exceptions.rpt]
report_drc -file [file join $reports drc.rpt]
report_utilization -file [file join $reports utilization.rpt]
report_io -file [file join $reports io.rpt]
foreach d {max min} {
 report_timing -from [get_ports {adc_data_p[*]}] -delay_type $d -max_paths 40 -path_type full_clock_expanded -file [file join $reports adc_$d.rpt]
 report_timing -from [get_cells -hier -filter {REF_NAME == ISERDESE2}] -delay_type $d -max_paths 20 -path_type full_clock_expanded -file [file join $reports parallel_$d.rpt]
}
for {set lane 0} {$lane < 14} {incr lane} {
 foreach d {max min} {
  foreach edge {rise fall} {
   # A clock object for -rise_to/-fall_to selects the capture clock edge,
   # rather than merely the data transition polarity.
   report_timing -from [get_ports [format {adc_data_p[%d]} $lane]] -${edge}_to [get_clocks adc_dco] -delay_type $d -max_paths 1 -path_type full_clock_expanded -file [file join $reports adc_lane${lane}_${edge}_${d}.rpt]
  }
 }
}
write_checkpoint -force [file join $reports routed.dcp]
set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]]
set whs [get_property SLACK [get_timing_paths -delay_type min -max_paths 1]]
set errors [get_drc_violations -filter {SEVERITY == Error}]
set latches [get_cells -hier -filter {REF_NAME =~ LD*}]
set f [open [file join $reports check_timing.rpt] r];set check [read $f];close $f
set unconstrained 1;set noclock 1
regexp {There are ([0-9]+) register/latch pins with no clock} $check -> noclock
regexp {There are ([0-9]+) pins that are not constrained for maximum delay} $check -> unconstrained
set f [open [file join $reports timing_summary.rpt] r];set summary [read $f];close $f
if {![regexp {WNS\(ns\)[^\n]*\n[^\n]*\n([^\n]+)} $summary -> row]} {error "Missing design timing summary row"}
set values [regexp -all -inline {[-+]?[0-9]+(?:\.[0-9]+)?} $row]
if {[llength $values] != 12} {error "Unexpected design summary: $row"}
set tns [lindex $values 1];set ths [lindex $values 5];set wpws [lindex $values 8];set tpws [lindex $values 9]
set noinput -1;set nooutput -1;set partialin -1;set partialout -1
regexp {There are ([0-9]+) input ports with no input delay specified} $check -> noinput
regexp {There are ([0-9]+) ports with no output delay specified} $check -> nooutput
regexp {checking partial_input_delay \(([0-9]+)\)} $check -> partialin
regexp {checking partial_output_delay \(([0-9]+)\)} $check -> partialout
set coverage 1
for {set lane 0} {$lane < 14} {incr lane} {
 foreach d {max min} {foreach edge {rise fall} {
  set f [open [file join $reports adc_lane${lane}_${edge}_${d}.rpt] r];set pathtext [read $f];close $f
  if {![string match *Slack* $pathtext]} {set coverage 0}
 }}
}
set pass [expr {$wns >= 0 && $whs >= 0 && $tns == 0 && $ths == 0 && $wpws >= 0 && $tpws == 0 && ![llength $errors] && ![llength $latches] && !$noclock && !$unconstrained && $noinput == 0 && $nooutput == 0 && $partialin == 0 && $partialout == 0 && $coverage}]
set f [open [file join $reports signoff.txt] w]
puts $f "WNS=$wns TNS=$tns WHS=$whs THS=$ths WPWS=$wpws TPWS=$tpws DRC_ERRORS=[llength $errors] LATCHES=[llength $latches] NO_CLOCK=$noclock UNCONSTRAINED_INTERNAL=$unconstrained NO_INPUT=$noinput NO_OUTPUT=$nooutput PARTIAL_INPUT=$partialin PARTIAL_OUTPUT=$partialout ADC_14LANE_DDR_BOTH_EDGE_MAX_MIN=$coverage STA_PASS=$pass"
puts $f "Allowed no-input-delay exception: asynchronous rst_n only. Static output ports have no timed sink; see check_timing.rpt classification."
puts $f "M2: ADC125 DDR, PN9 trained capture, PS GP0. STA and simulation do not prove integrated hardware capture."
close $f
puts "M2_STA_PASS=$pass WNS=$wns WHS=$whs"
if {!$pass} {error "STA signoff failed; no hardware platform release permitted"}
# No bitstream is released automatically: preserve a reviewable routed checkpoint.
write_debug_probes -force [file join $root artifacts telecontrol_system.ltx]
