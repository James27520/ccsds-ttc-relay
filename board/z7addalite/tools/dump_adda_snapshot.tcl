# Read a published, cache-flushed DDR snapshot from the explicitly selected board.
# CPU execution is resumed only if this script successfully stopped it.
if {[llength $argv] != 3} {error "usage: dump_adda_snapshot.tcl <cable-serial> <DDR-address> <output.bin>"}
set serial [lindex $argv 0]
set address [lindex $argv 1]
set output [file normalize [lindex $argv 2]]
if {![regexp {^[A-Za-z0-9]+$} $serial]} {error "Invalid cable serial"}
if {![regexp {^0x[0-9a-fA-F]{8}$} $address]} {error "Expected explicit hexadecimal DDR address"}
set address [expr {$address}]
if {$address < 0x01000000 || $address+0x40000 > 0x40000000 || ($address & 3)} {error "Snapshot outside reviewed application DDR"}
if {[file exists $output]} {error "Refuse to overwrite a snapshot"}
connect -url tcp:127.0.0.1:3121
set cpus [targets -target-properties -filter "name =~ \"ARM*#0\" && jtag_cable_serial == \"$serial\""]
set fpgas [targets -target-properties -filter "name == \"xc7z020\" && jtag_cable_serial == \"$serial\""]
if {[llength $cpus] != 1 || [llength $fpgas] != 1} {error "Expected one exact Z7ADDALite cable and XC7Z020"}
targets -set [dict get [lindex $cpus 0] target_id]
set resume 0
if {[catch {stop} reason]} {
 if {![string match "*Already stopped*" $reason]} {error $reason}
} else {set resume 1}
set result [catch {mrd -bin -file $output $address 65536} reason]
if {$resume} {con}
disconnect
if {$result} {error $reason}
if {[file size $output] != 262144} {error "Snapshot must contain exactly 131072 int16 samples"}
puts "DDR_SNAPSHOT bytes=[file size $output] address=[format 0x%08X $address] cable=$serial"
exit
