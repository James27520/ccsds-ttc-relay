open_project E:/LDSDR_010/zynq_dev_fmcomms3.xpr
open_bd_design [get_files design_1.bd]
set ps [get_bd_cells processing_system7_0]
puts "===== SD ?? ====="
foreach p {PCW_SD0_PERIPHERAL_ENABLE PCW_SD0_SD0_IO PCW_SDIO_PERIPHERAL_FREQMHZ PCW_SD0_GRP_INT PCW_SD0_GRP_POW PCW_SD0_GRP_WP PCW_SD0_GRP_CD PCW_SD0_GRP_BUS_WIDTH} {
  if {[catch {get_property CONFIG.$p $ps} v]} { set v "(???)" }
  puts "  $p = $v"
}
puts "===== MIO ?? ====="
foreach p {PCW_MIO_40 PCW_MIO_41 PCW_MIO_42 PCW_MIO_43 PCW_MIO_44 PCW_MIO_45} {
  if {[catch {get_property CONFIG.$p $ps} v]} { set v "(???)" }
  puts "  $p = $v"
}
puts "===== FCLK?PL ???????? ====="
foreach p {PCW_FPGA0_PERIPHERAL_FREQMHZ PCW_FPGA1_PERIPHERAL_FREQMHZ PCW_FPGA2_PERIPHERAL_FREQMHZ PCW_FPGA3_PERIPHERAL_FREQMHZ PCW_ACT_FPGA0_ENABLE PCW_ACT_FPGA1_ENABLE} {
  if {[catch {get_property CONFIG.$p $ps} v]} { set v "(???)" }
  puts "  $p = $v"
}
puts "===== ????? MIO ====="
foreach p {PCW_UART1_PERIPHERAL_ENABLE PCW_UART1_UART1_IO PCW_SPI0_PERIPHERAL_ENABLE PCW_SPI0_SPI0_IO PCW_GPIO_MIO_GPIO_ENABLE PCW_EN_CLK0_PORT PCW_EN_CLK1_PORT} {
  if {[catch {get_property CONFIG.$p $ps} v]} { set v "(???)" }
  puts "  $p = $v"
}
