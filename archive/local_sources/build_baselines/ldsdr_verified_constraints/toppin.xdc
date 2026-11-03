
set_property -dict {PACKAGE_PIN N20 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports rx_clk_in_p]
set_property -dict {PACKAGE_PIN P20 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports rx_clk_in_n]
set_property -dict {PACKAGE_PIN Y16 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports rx_frame_in_p]
set_property -dict {PACKAGE_PIN Y17 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports rx_frame_in_n]
set_property -dict {PACKAGE_PIN Y18 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_p[0]}]
set_property -dict {PACKAGE_PIN Y19 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_n[0]}]
set_property -dict {PACKAGE_PIN V17 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_p[1]}]
set_property -dict {PACKAGE_PIN V18 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_n[1]}]
set_property -dict {PACKAGE_PIN W18 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_p[2]}]
set_property -dict {PACKAGE_PIN W19 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_n[2]}]
set_property -dict {PACKAGE_PIN R16 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_p[3]}]
set_property -dict {PACKAGE_PIN R17 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_n[3]}]
set_property -dict {PACKAGE_PIN V20 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_p[4]}]
set_property -dict {PACKAGE_PIN W20 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_n[4]}]
set_property -dict {PACKAGE_PIN W14 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_p[5]}]
set_property -dict {PACKAGE_PIN Y14 IOSTANDARD LVDS_25 DIFF_TERM 1} [get_ports {rx_data_in_n[5]}]

set_property -dict {PACKAGE_PIN N18 IOSTANDARD LVDS_25} [get_ports tx_clk_out_p]
set_property -dict {PACKAGE_PIN P19 IOSTANDARD LVDS_25} [get_ports tx_clk_out_n]
set_property -dict {PACKAGE_PIN V16 IOSTANDARD LVDS_25} [get_ports tx_frame_out_p]
set_property -dict {PACKAGE_PIN W16 IOSTANDARD LVDS_25} [get_ports tx_frame_out_n]
set_property -dict {PACKAGE_PIN T16 IOSTANDARD LVDS_25} [get_ports {tx_data_out_p[0]}]
set_property -dict {PACKAGE_PIN U17 IOSTANDARD LVDS_25} [get_ports {tx_data_out_n[0]}]
set_property -dict {PACKAGE_PIN U18 IOSTANDARD LVDS_25} [get_ports {tx_data_out_p[1]}]
set_property -dict {PACKAGE_PIN U19 IOSTANDARD LVDS_25} [get_ports {tx_data_out_n[1]}]
set_property -dict {PACKAGE_PIN U14 IOSTANDARD LVDS_25} [get_ports {tx_data_out_p[2]}]
set_property -dict {PACKAGE_PIN U15 IOSTANDARD LVDS_25} [get_ports {tx_data_out_n[2]}]
set_property -dict {PACKAGE_PIN V12 IOSTANDARD LVDS_25} [get_ports {tx_data_out_p[3]}]
set_property -dict {PACKAGE_PIN W13 IOSTANDARD LVDS_25} [get_ports {tx_data_out_n[3]}]
set_property -dict {PACKAGE_PIN T12 IOSTANDARD LVDS_25} [get_ports {tx_data_out_p[4]}]
set_property -dict {PACKAGE_PIN U12 IOSTANDARD LVDS_25} [get_ports {tx_data_out_n[4]}]
set_property -dict {PACKAGE_PIN V15 IOSTANDARD LVDS_25} [get_ports {tx_data_out_p[5]}]
set_property -dict {PACKAGE_PIN W15 IOSTANDARD LVDS_25} [get_ports {tx_data_out_n[5]}]

set_property -dict {PACKAGE_PIN U13 IOSTANDARD LVCMOS25} [get_ports {ctrl_in[0]}]
set_property -dict {PACKAGE_PIN T14 IOSTANDARD LVCMOS25} [get_ports {ctrl_in[1]}]
set_property -dict {PACKAGE_PIN V13 IOSTANDARD LVCMOS25} [get_ports {ctrl_in[2]}]
set_property -dict {PACKAGE_PIN T11 IOSTANDARD LVCMOS25} [get_ports {ctrl_in[3]}]
set_property -dict {PACKAGE_PIN P16 IOSTANDARD LVCMOS25} [get_ports en_agc]
#set_property -dict {PACKAGE_PIN G16     IOSTANDARD LVCMOS25} [get_ports sync_in]                          ; ## H23  FMC_LPC_LA19_N
set_property -dict {PACKAGE_PIN T17 IOSTANDARD LVCMOS25} [get_ports resetb]
set_property -dict {PACKAGE_PIN R18 IOSTANDARD LVCMOS25} [get_ports enable]
set_property -dict {PACKAGE_PIN N17 IOSTANDARD LVCMOS25} [get_ports txnrx]


set_property PACKAGE_PIN T20 [get_ports spi_csn]
set_property IOSTANDARD LVCMOS25 [get_ports spi_csn]
set_property PULLUP true [get_ports spi_csn]
set_property -dict {PACKAGE_PIN R19 IOSTANDARD LVCMOS25} [get_ports spi_clk]
set_property -dict {PACKAGE_PIN P18 IOSTANDARD LVCMOS25} [get_ports spi_mosi]
set_property -dict {PACKAGE_PIN T19 IOSTANDARD LVCMOS25} [get_ports spi_miso]

#-----------------------------------------------------------------------------
# DATA_CLK (= rx_clk_in) period.
#
# 2R2T LVDS mode: DATA_CLK = 4 x per-channel sample rate (see phy_rx.v /
# dds_dq.v: the frame shift register produces one sample set every 4 clocks).
#   30.72 MSPS per channel  ->  DATA_CLK = 122.88 MHz  ->  8.138 ns
#   61.44 MSPS per channel  ->  DATA_CLK = 245.76 MHz  ->  4.069 ns
# 1R1T mode: DATA_CLK = sample rate, which is always slower than the 2R2T
# case above, so this value covers both modes.
#
# The original value (4.069 ns) is the ADI reference design figure for the
# maximum 61.44 MSPS rate.  Keeping it here made the whole data_clk domain
# unrealistically hard - even the vendor's own design failed it
# (WNS = -2.692 ns, 129 failing endpoints).
#
# !! If you change `sample_rate` in main.c, update this number:
#       period_ns = 4000 / (sample_rate_in_MSPS)      for 2R2T
#-----------------------------------------------------------------------------
create_clock -period 8.138 -name rx_clk [get_ports rx_clk_in_p]

#-----------------------------------------------------------------------------
# Clock groups: declare the genuinely asynchronous clock domains.
#
# rx_clk (the AD9361 DATA_CLK) is unrelated to the PS AXI clock and to the
# ILA clock.  Every crossing between them is handled explicitly in the RTL:
#
#   clk_fpga_0 -> rx_clk  : relay_cdc_word      (2-flop sync + stability filter)
#   rx_clk -> clk_fpga_0  : relay_counter_snap  (shadow register + toggle ack)
#   anything -> ILA clock : observation only, the ILA is a debug port
#
# Without this, Vivado tries to time those crossings against each other and
# reports them as violations (it reported -8.67 ns and 224 failing endpoints
# for rx_clk -> ILA alone, purely because the two clocks have no common
# period).  These are NOT real logic paths.
#-----------------------------------------------------------------------------
set_clock_groups -asynchronous \
    -group [get_clocks -quiet rx_clk] \
    -group [get_clocks -quiet clk_fpga_0] \
    -group [get_clocks -quiet clk_fpga_1] \
    -group [get_clocks -quiet -include_generated_clocks sys_clk]


set_property PACKAGE_PIN K17 [get_ports sys_clk]
set_property IOSTANDARD LVCMOS25 [get_ports sys_clk]
