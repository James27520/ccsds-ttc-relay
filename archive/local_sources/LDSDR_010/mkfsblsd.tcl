setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
puts "=== ? fsbl_sd ==="
if {[catch {createapp -name fsbl_sd -hwproject relay_sd_hw -bsp fsbl_sd_bsp -proc ps7_cortexa9_0 -os standalone -lang c -app "Zynq FSBL"} e]} {
  puts "  ??: $e"
} else { puts "  ??" }
puts "=== ??? fsbl_sd ==="
catch {projects -build -type app -project fsbl_sd} b
puts $b
puts "=== ?? ==="
foreach f [glob -nocomplain "E:/LDSDR_010/zynq_dev_fmcomms3.sdk/fsbl_sd/Debug/*.elf"] {
  puts "  $f  ([file size $f] ??)"
}
