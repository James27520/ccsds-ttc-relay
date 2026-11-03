setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
puts "=== bsp ?????? ==="
puts [lsort [info commands *lib*]]
puts ""
puts "=== ? fsbl_sd_bsp ? xilffs ==="
foreach cmd {
  {bsp setlib -name xilffs -bsp fsbl_sd_bsp}
  {setlib -lib xilffs -bsp fsbl_sd_bsp}
  {bsp setlib -lib xilffs -bsp fsbl_sd_bsp}
} {
  if {[catch {eval $cmd} e]} { puts "  [lindex $cmd 0] [lindex $cmd 1] -> $e" } else { puts "  ??: $cmd"; break }
}
puts ""
puts "=== ?? xilffs ??? ==="
catch {bsp listlib -bsp fsbl_sd_bsp} L
puts $L
