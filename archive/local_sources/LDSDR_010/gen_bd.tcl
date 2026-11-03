open_project E:/LDSDR_010/zynq_dev_fmcomms3.xpr
set bd [get_files design_1.bd]
puts "===== ???? BD ???? ====="
generate_target all $bd
puts "  generate_target ??"
puts "===== ?????? ====="
write_hwdef -force -file E:/LDSDR_010/relay_sd_hw/system.hdf
puts "  hdf: [file size E:/LDSDR_010/relay_sd_hw/system.hdf] ??"
puts "===== ?? FCLK ?? ====="
open_bd_design $bd
set ps [get_bd_cells processing_system7_0]
foreach p {PCW_FPGA0_PERIPHERAL_FREQMHZ PCW_FPGA1_PERIPHERAL_FREQMHZ PCW_SD0_PERIPHERAL_ENABLE PCW_SD0_SD0_IO PCW_SDIO_PERIPHERAL_FREQMHZ} {
  if {[catch {get_property CONFIG.$p $ps} v]} { set v "?" }
  puts "  $p = $v"
}
puts "===== ?????? ====="
puts "  [file exists E:/LDSDR_010/zynq_dev_fmcomms3.runs/impl_2/ad9361_top.bit]"
close_project
