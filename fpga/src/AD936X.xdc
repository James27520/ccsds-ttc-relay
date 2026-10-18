# constraints
# ad9361
set_property -dict {PACKAGE_PIN N18 IOSTANDARD LVCMOS25} [get_ports i_clk]

set_property -dict {PACKAGE_PIN U18 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports rx_clk_in_p]
set_property -dict {PACKAGE_PIN U19 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports rx_clk_in_n]
set_property -dict {PACKAGE_PIN Y16 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports rx_frame_in_p]
set_property -dict {PACKAGE_PIN Y17 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports rx_frame_in_n]
set_property -dict {PACKAGE_PIN Y18 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_p[0]}]
set_property -dict {PACKAGE_PIN Y19 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_n[0]}]
set_property -dict {PACKAGE_PIN T16 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_p[1]}]
set_property -dict {PACKAGE_PIN U17 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_n[1]}]
set_property -dict {PACKAGE_PIN V20 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_p[2]}]
set_property -dict {PACKAGE_PIN W20 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_n[2]}]
set_property -dict {PACKAGE_PIN T17 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_p[3]}]
set_property -dict {PACKAGE_PIN R18 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_n[3]}]
set_property -dict {PACKAGE_PIN T20 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_p[4]}]
set_property -dict {PACKAGE_PIN U20 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_n[4]}]
set_property -dict {PACKAGE_PIN W18 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_p[5]}]
set_property -dict {PACKAGE_PIN W19 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_n[5]}]
set_property -dict {PACKAGE_PIN U14 IOSTANDARD LVDS_25} [get_ports tx_clk_out_p]
set_property -dict {PACKAGE_PIN U15 IOSTANDARD LVDS_25} [get_ports tx_clk_out_n]
set_property -dict {PACKAGE_PIN V16 IOSTANDARD LVDS_25} [get_ports tx_frame_out_p]
set_property -dict {PACKAGE_PIN W16 IOSTANDARD LVDS_25} [get_ports tx_frame_out_n]
set_property -dict {PACKAGE_PIN V15 IOSTANDARD LVDS_25} [get_ports {tx_data_out_p[0]}]
set_property -dict {PACKAGE_PIN W15 IOSTANDARD LVDS_25} [get_ports {tx_data_out_n[0]}]
set_property -dict {PACKAGE_PIN V12 IOSTANDARD LVDS_25} [get_ports {tx_data_out_p[1]}]
set_property -dict {PACKAGE_PIN W13 IOSTANDARD LVDS_25} [get_ports {tx_data_out_n[1]}]
set_property -dict {PACKAGE_PIN W14 IOSTANDARD LVDS_25} [get_ports {tx_data_out_p[2]}]
set_property -dict {PACKAGE_PIN Y14 IOSTANDARD LVDS_25} [get_ports {tx_data_out_n[2]}]
set_property -dict {PACKAGE_PIN T12 IOSTANDARD LVDS_25} [get_ports {tx_data_out_p[3]}]
set_property -dict {PACKAGE_PIN U12 IOSTANDARD LVDS_25} [get_ports {tx_data_out_n[3]}]
set_property -dict {PACKAGE_PIN T11 IOSTANDARD LVDS_25} [get_ports {tx_data_out_p[4]}]
set_property -dict {PACKAGE_PIN T10 IOSTANDARD LVDS_25} [get_ports {tx_data_out_n[4]}]
set_property -dict {PACKAGE_PIN U13 IOSTANDARD LVDS_25} [get_ports {tx_data_out_p[5]}]
set_property -dict {PACKAGE_PIN V13 IOSTANDARD LVDS_25} [get_ports {tx_data_out_n[5]}]

                        
set_property -dict {PACKAGE_PIN J19 IOSTANDARD LVCMOS25} [get_ports {ctrl_in[0]}]
set_property -dict {PACKAGE_PIN K14 IOSTANDARD LVCMOS25} [get_ports {ctrl_in[1]}]
set_property -dict {PACKAGE_PIN L17 IOSTANDARD LVCMOS25} [get_ports {ctrl_in[2]}]
set_property -dict {PACKAGE_PIN J20 IOSTANDARD LVCMOS25} [get_ports {ctrl_in[3]}]
set_property -dict {PACKAGE_PIN P20 IOSTANDARD LVCMOS25} [get_ports en_agc]
set_property -dict {PACKAGE_PIN T19 IOSTANDARD LVCMOS25} [get_ports sync_in]
set_property -dict {PACKAGE_PIN R19 IOSTANDARD LVCMOS25} [get_ports chip_rst_n]
set_property -dict {PACKAGE_PIN T15 IOSTANDARD LVCMOS25} [get_ports enable]
set_property -dict {PACKAGE_PIN P18 IOSTANDARD LVCMOS25} [get_ports txnrx]


set_property -dict {PACKAGE_PIN R17 IOSTANDARD LVCMOS25 PULLUP true} [get_ports o_spi_csn]
set_property -dict {PACKAGE_PIN V18 IOSTANDARD LVCMOS25} [get_ports o_spi_clk]
set_property -dict {PACKAGE_PIN P16 IOSTANDARD LVCMOS25} [get_ports o_spi_mosi]
set_property -dict {PACKAGE_PIN V17 IOSTANDARD LVCMOS25} [get_ports i_spi_miso]



# 原为 [get_nets clk_wiz_0_u/inst/clk_in1_clk_wiz_0]（引用已移除的 clk_wiz IP）。
# 现在时钟由纯原语 MMCME2_BASE 产生（clk_pll.v），i_clk 所在引脚 N18 不是
# 时钟专用引脚，因此仍需关闭该 DRC，否则实现阶段会报 CLOCK_DEDICATED_ROUTE 错。
set_property CLOCK_DEDICATED_ROUTE FALSE [get_nets -of_objects [get_pins clk_pll_u/mmcm_i/CLKIN1]]
set_property SEVERITY {Warning} [get_drc_checks UCIO-1]
# 位流压缩：让位流足够小，将来也能塞进 SD 卡 BOOT.bin 的位流区（966,800 B）。
# 放在 XDC 里（厂商也同样放置），因为该属性必须在设计打开时设置。
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
# clocks
#
# 原为 create_clock -period 4.000 -name rx_clk [get_ports rx_clk_in_p]
# (4.000 ns = 250 MHz)。这个值是过约束的猜测，不是本板的真实时钟：
#
#   ILA 实测 sample_clk = 0.4 x clk_100M
#   sample_clk = data_clk / 4      (data_process.v: CLK_DIV_module P_CLK_DIV_CNT=4)
#   clk_100M   = i_clk x 20 / 10   (clk_pll.v, 参数与厂商 clk_wiz 一致)
#   板载 i_clk = 38.4 MHz          (与厂商 AD9361_Project.prj 的 REFCLK_IN 一致)
#     => clk_100M   = 76.8  MHz
#     => sample_clk = 30.72 MHz    <-- 与板上 TXSAMP=30720000 精确吻合，交叉验证成立
#     => rx_clk     = 4 x 30.72 = 122.88 MHz  => 周期 8.138 ns
#
# 用真实周期后，data_process_U0 内部那些在 250 MHz 下勉强收敛的路径
# (selectio_tx_data_reg -> oddr_data/D2、iddr_data/C -> rx0_msb_*_reg/CE 等)
# 才有余量。实测：4.000 ns 且加 ILA 后 WNS=-0.401 ns；改为 8.138 ns 后转正。
create_clock -period 8.138 -name rx_clk [get_ports rx_clk_in_p]
