setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
puts "--- building project 9361 ---"
if {[catch {projects -build -name 9361} msg]} {
    puts "named-build failed: $msg"
    puts "--- falling back to build-all ---"
    catch {projects -build} msg2
    puts "build-all: $msg2"
}
puts "--- elf ---"
foreach f [glob -nocomplain "E:/LDSDR_010/zynq_dev_fmcomms3.sdk/9361/Debug/*.elf"] {
    puts "  $f  ([file size $f] bytes)"
}
