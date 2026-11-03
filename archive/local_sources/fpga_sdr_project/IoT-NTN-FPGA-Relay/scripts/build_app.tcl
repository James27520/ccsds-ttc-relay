setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
puts "--- building all projects ---"
puts [projects -build]
puts "--- elf ---"
foreach f [glob -nocomplain "E:/LDSDR_010/zynq_dev_fmcomms3.sdk/9361/Debug/*.elf"] {
    puts "  $f  ([file size $f] bytes)"
}
