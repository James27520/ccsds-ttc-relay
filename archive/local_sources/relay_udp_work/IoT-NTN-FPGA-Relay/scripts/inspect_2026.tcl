# Inspect a copied project without upgrading or changing its IP.
if {[llength $argv] != 2} { error "usage: inspect_2026.tcl <copy.xpr> <report.txt>" }
open_project -read_only [lindex $argv 0]
puts "RELAY_PROJECT_PART=[get_property PART [current_project]]"
puts "RELAY_PROJECT_TOP=[get_property TOP [get_filesets sources_1]]"
report_ip_status -file [lindex $argv 1]
close_project
exit
