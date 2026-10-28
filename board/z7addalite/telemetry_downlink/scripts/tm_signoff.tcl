# Additional DAC coverage and CDC-bundle checks; base r4c STA gates run first.
set fp [open [file join $root reports tm_signoff.txt] w]
set paths_checked 0
set worst 1000
for {set lane 0} {$lane < 16} {incr lane} {
 foreach delay {max min} {foreach edge {rise fall} {
  set port [get_ports [format {dac_data_p[%d]} $lane]]
  set paths [get_timing_paths -quiet -to $port -${edge}_to [get_clocks tm_dac_capture] -delay_type $delay -max_paths 1]
  if {[llength $paths] != 1} {error "Missing DAC lane $lane $edge $delay path"}
  set slack [get_property SLACK [lindex $paths 0]]
  if {$slack < 0} {error "DAC lane $lane $edge $delay failed $slack"}
  if {$slack < $worst} {set worst $slack}
  puts $fp "DAC_LANE=$lane EDGE=$edge DELAY=$delay SLACK=$slack"
  report_timing -to $port -${edge}_to [get_clocks tm_dac_capture] -delay_type $delay -max_paths 1 -path_type full_clock_expanded -file [file join $root reports tm_dac_${lane}_${edge}_${delay}.rpt]
  incr paths_checked
 }}
}
foreach {mailbox required} {tm_cmd_mailbox 3.0 tm_done_mailbox 20.0} {
 set endpoints [get_pins -hier -regexp [format {tm_transmitter/%s/data_meta_reg\[[0-9]+\]/D} $mailbox]]
 if {[llength $endpoints]==0} {error "Missing $mailbox"}
 foreach pin $endpoints {
  set paths [get_timing_paths -quiet -to $pin -delay_type max -max_paths 1]
  if {[llength $paths]!=1} {error "Missing dynamic bundle path $pin"}
  set path [lindex $paths 0]
  if {abs([get_property REQUIREMENT $path]-$required)>0.001 || [get_property SLACK $path]<0} {error "Bundle timing failed at $pin"}
  puts $fp "BUNDLE=$pin REQUIREMENT=[get_property REQUIREMENT $path] SLACK=[get_property SLACK $path]"
 }
}
puts $fp "DAC_16LANE_DDR_BOTH_EDGE_MAX_MIN=$paths_checked WORST_SLACK=$worst TM_STA_PASS=1"
puts $fp "This is digital STA with assumed 100ps PCB skew, not analog RF acceptance."
close $fp
puts "TM_STA_PASS=1 DAC_PATHS=$paths_checked WORST_SLACK=$worst"
