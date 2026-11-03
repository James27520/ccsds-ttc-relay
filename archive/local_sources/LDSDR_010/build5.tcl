setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
puts "STEP1 regen bsp"
set r1 [catch {regenbsp -bsp fsblsd_bsp} e1]
puts "  rc=$r1 err=$e1"
puts "STEP2 build projects"
set r2 [catch {projects -build} e2]
puts "  rc=$r2 err=$e2"
puts "STEP3 list elf"
foreach f [glob -nocomplain "E:/LDSDR_010/zynq_dev_fmcomms3.sdk/*/Debug/*.elf"] {
  puts "  ELF: $f  [file size $f]"
}
