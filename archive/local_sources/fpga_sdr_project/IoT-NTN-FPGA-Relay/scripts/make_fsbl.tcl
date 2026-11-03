setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
puts "=== available app templates ==="
catch {repo -apps} t
puts $t
puts "=== creating fsbl ==="
if {[catch {
    createapp -name fsbl -app "Zynq FSBL" -proc ps7_cortexa9_0 \
              -hwproject ad9361_top_hw_platform_0 -os standalone
} e]} { puts "create failed: $e" } else { puts "FSBL project created" }
puts "=== building ==="
catch {projects -build} b
foreach f [glob -nocomplain "E:/LDSDR_010/zynq_dev_fmcomms3.sdk/fsbl/Debug/*.elf"] {
    puts "FSBL -> $f ([file size $f] bytes)"
}
