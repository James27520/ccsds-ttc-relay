setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
set rc [catch {createapp -name fsbl_sd -hwproject relay_sd_hw -bsp fsbl_sd_bsp -proc ps7_cortexa9_0 -os standalone -lang c -app {Zynq FSBL}} err]
puts "CREATE_RC=$rc"
puts "CREATE_ERR=$err"
puts "PROJECTS: [projects]"
