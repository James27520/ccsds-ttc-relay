open_project E:/LDSDR_010/zynq_dev_fmcomms3.xpr
open_bd_design [get_files design_1.bd]
set ps [get_bd_cells processing_system7_0]

puts "===== ??? FCLK ====="
foreach p {PCW_FPGA0_PERIPHERAL_FREQMHZ PCW_FPGA1_PERIPHERAL_FREQMHZ PCW_UART1_UART1_IO PCW_SPI0_SPI0_IO PCW_GPIO_MIO_GPIO_ENABLE} {
  if {[catch {get_property CONFIG.$p $ps} v]} { set v "?" }
  puts "  $p = $v"
}

set_property -dict [list \
    CONFIG.PCW_SD0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_SD0_SD0_IO {MIO 40 .. 45} \
    CONFIG.PCW_SDIO_PERIPHERAL_FREQMHZ {50} \
] $ps

puts "===== ??? ====="
foreach p {PCW_SD0_PERIPHERAL_ENABLE PCW_SD0_SD0_IO PCW_SDIO_PERIPHERAL_FREQMHZ PCW_FPGA0_PERIPHERAL_FREQMHZ PCW_FPGA1_PERIPHERAL_FREQMHZ} {
  if {[catch {get_property CONFIG.$p $ps} v]} { set v "?" }
  puts "  $p = $v"
}

validate_bd_design
save_bd_design
puts "===== ???? ====="
file mkdir E:/LDSDR_010/relay_sd_hw
write_hwdef -force -file E:/LDSDR_010/relay_sd_hw/system.hdf
puts "  hdf: [file size E:/LDSDR_010/relay_sd_hw/system.hdf] ??"
close_project
