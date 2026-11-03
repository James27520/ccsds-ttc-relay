setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
set rc [catch {createapp -name fsbl_sd -app {Zynq FSBL} -proc ps7_cortexa9_0 -hwproject relay_sd_hw -os standalone} e]
puts "CREATE_RC=$rc"
puts "CREATE_ERR=$e"
if {$rc == 0} {
  puts "BUILDING..."
  catch {projects -build -type app -project fsbl_sd} b
  foreach f [glob -nocomplain "E:/LDSDR_010/zynq_dev_fmcomms3.sdk/fsbl_sd/Debug/*.elf"] {
    puts "FSBL_ELF=$f SIZE=[file size $f]"
  }
}
