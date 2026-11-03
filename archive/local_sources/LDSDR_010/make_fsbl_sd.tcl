setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
puts "=== ????? ==="
if {[catch {createhw -name relay_sd_hw -hwspec E:/LDSDR_010/relay_sd_hw/system.hdf} e]} { puts "  ??: $e" } else { puts "  OK" }
puts "=== ? FSBL BSP ==="
if {[catch {createbsp -name fsbl_sd_bsp -hwproject relay_sd_hw -proc ps7_cortexa9_0 -os standalone} e]} { puts "  ??: $e" } else { puts "  OK" }
puts "=== ? FSBL ?? ==="
if {[catch {createapp -name fsbl_sd -hwproject relay_sd_hw -bsp fsbl_sd_bsp -proc ps7_cortexa9_0 -os standalone -app "Zynq FSBL"} e]} { puts "  ??: $e" } else { puts "  OK" }
puts "=== ?? ==="
catch {projects -build} b
foreach f [glob -nocomplain "E:/LDSDR_010/zynq_dev_fmcomms3.sdk/fsbl_sd/Debug/*.elf"] {
    puts "  FSBL -> $f ([file size $f] ??)"
}
