setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
set rc [catch {regenbsp -bsp fsbl_bsp} e]
puts "REGEN_RC=$rc"
puts "REGEN_ERR=$e"
