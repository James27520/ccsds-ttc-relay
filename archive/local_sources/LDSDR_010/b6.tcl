setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
catch {projects -build} b
puts "BUILD_DONE"
foreach f [glob -nocomplain "E:/LDSDR_010/zynq_dev_fmcomms3.sdk/*/Debug/*.elf"] {
  puts "ELF: $f  [file size $f]"
}
