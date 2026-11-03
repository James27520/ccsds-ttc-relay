setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
foreach n {fsblsd fsblsd_bsp} {
  if {[llength [glob -nocomplain E:/LDSDR_010/zynq_dev_fmcomms3.sdk/$n]]} {
    file delete -force E:/LDSDR_010/zynq_dev_fmcomms3.sdk/$n
  }
}
set rc [catch {createapp -name fsblsd -app {Zynq FSBL} -proc ps7_cortexa9_0 -hwproject relay_sd_hw -os standalone} e]
puts "CREATE_RC=$rc"
puts "CREATE_ERR=$e"
if {$rc == 0} {
  puts "BUILDING..."
  catch {projects -build -type app -project fsblsd} b
  foreach f [glob -nocomplain "E:/LDSDR_010/zynq_dev_fmcomms3.sdk/fsblsd/Debug/*.elf"] {
    puts "FSBL_ELF=$f SIZE=[file size $f]"
  }
}
