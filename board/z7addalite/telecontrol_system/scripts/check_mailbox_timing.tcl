# Verify actual timing paths, not merely that a constraint command matched.
proc check_mailbox_timing {out_file} {
 set fp [open $out_file w]
 set total 0
 foreach mb {config_mailbox capture_path/command_mailbox capture_path/event_mailbox capture_path/training_mailbox} {
  set src [get_cells -hier -regexp [format {%s/held_data_reg\[[0-9]+\]} $mb]]
  set dst [get_pins -hier -regexp [format {%s/data_meta_reg\[[0-9]+\]/D} $mb]]
  if {![llength $dst]} {error "Missing held-data CDC endpoints in $mb"}
  set checked 0
  set constants 0
  set worst 1000.0
  foreach pin $dst {
   # Launch cells may merge with an equivalent register outside the mailbox
   # (published_epoch/training_sent). Query the actual destination cone.
   set paths [get_timing_paths -quiet -to $pin -delay_type max -max_paths 1]
   if {[llength $paths] != 1} {
    # ASYNC_REG can retain a first-stage FF whose data optimized to a constant.
    # Only direct GND/VCC drivers are exempt; a missing dynamic path is fatal.
    set drivers [get_cells -of_objects [get_pins -leaf -of_objects [get_nets -of_objects $pin] -filter {DIRECTION == OUT}]]
    if {[llength $drivers] == 1 && [get_property REF_NAME $drivers] in {GND VCC}} {
     puts $fp "CONSTANT_ENDPOINT=$pin DRIVER=[get_property REF_NAME $drivers]"
     incr constants
     continue
    }
    error "Untimed/false-pathed nonconstant mailbox endpoint: $pin; drivers=$drivers"
   }
   set path [lindex $paths 0]
   set requirement [get_property REQUIREMENT $path]
   set slack [get_property SLACK $path]
   if {abs($requirement - 20.0) > 0.001} {error "Wrong mailbox max-delay $requirement for $pin"}
   if {$slack < 0} {error "Mailbox datapath delay exceeds 20ns at $pin: slack=$slack"}
   if {$slack < $worst} {set worst $slack}
   puts $fp "ENDPOINT=$pin LAUNCH=[get_property STARTPOINT_PIN $path] REQUIREMENT=$requirement SLACK=$slack"
   incr checked
  }
  if {$checked == 0} {error "No dynamic mailbox bits checked in $mb"}
  puts $fp "MAILBOX=$mb SOURCE_REGS=[llength $src] DESTINATION_BITS=[llength $dst] CHECKED=$checked CONSTANT_BITS=$constants WORST_SLACK=$worst"
  report_timing -to $dst -delay_type max -max_paths 5 -path_type full -file [file rootname $out_file]_[string map {/ _} $mb].rpt
  incr total $checked
 }
 puts $fp "MAILBOX_TIMED_BITS=$total MAX_DELAY_NS=20.000 PASS=1"
 close $fp
 puts "MAILBOX_TIMED_BITS=$total MAX_DELAY_NS=20.000 PASS=1"
}
