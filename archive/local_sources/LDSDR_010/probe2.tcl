puts "=== program_flash ???? SD ? ==="
if {[catch {program_flash -help} h]} { puts "? program_flash" } else {
  foreach line [split $h "\n"] {
    if {[string match "*flash_type*" $line] || [string match "*sd*" $line] || [string match "*qspi*" $line]} { puts "  $line" }
  }
}
puts ""
puts "=== BSP ????? xilffs (FAT ????) ? ==="
setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
catch {repo -libs} libs
puts $libs
