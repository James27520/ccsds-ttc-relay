# AD9122 Rev.C Table13, DCI delay register 0x16=3, word-mode DDR.
# Data is edge aligned with DCI at the package. The abstract +1ns reference
# translates ts=-0.47ns/th=1.38ns into .53/.38ns; add 0.1ns PCB skew budget.
# Board skew is an assumption, not an oscilloscope measurement.
create_generated_clock -name tm_dac_capture -source [get_pins tm_output/dci_reg/C] -edges {1 2 3} -edge_shift {1.000 1.000 1.000} [get_ports dac_dci_p]
set_clock_uncertainty 0.100 [get_clocks clk_out1_clk_wiz_tm]
set_output_delay -clock tm_dac_capture -max 0.630 [get_ports {dac_data_p[*]}]
set_output_delay -clock tm_dac_capture -min -0.480 [get_ports {dac_data_p[*]}]
set_output_delay -clock tm_dac_capture -clock_fall -add_delay -max 0.630 [get_ports {dac_data_p[*]}]
set_output_delay -clock tm_dac_capture -clock_fall -add_delay -min -0.480 [get_ports {dac_data_p[*]}]
set_output_delay -clock spi_budget -max 20.000 [get_ports {dac_sclk dac_sda dac_cs dac_rstn}]
set_output_delay -clock spi_budget -min 0.000 [get_ports {dac_sclk dac_sda dac_cs dac_rstn}]
set_input_delay -clock spi_budget -min 0.000 [get_ports dac_sda]
set_input_delay -clock spi_budget -max 20.000 [get_ports dac_sda]
# Narrow first-stage exceptions only. Payloads and DAC lanes remain timed.
set_false_path -to [get_pins -hier -regexp {tm_config_sync_reg\[0\]/D|tm_transmitter/(cfg_sync_reg|active_sync_reg|stop_ack_sync_reg|stop_sync_reg)\[0\]/D}]
set_false_path -to [get_pins -hier -regexp {(tm_ctrl_reset_sync_reg|tm_dac_reset_sync_reg)\[[0-9]+\]/PRE|tm_config_sync_reg\[[0-9]+\]/CLR|tm_output/(dci_reg|lanes\[[0-9]+\].data_reg)/R}]
# Async ODDR reset-to-Q arcs also reach the output ports. Only these reset
# arcs are exempt; D1/D2-to-pin setup/hold remains fully constrained. Reset
# release is held by tm_dac_reset_sync until three running DAC clock edges.
set_false_path -through [get_pins -hier -regexp {tm_output/(dci_reg|lanes\[[0-9]+\].data_reg)/R}]
set_false_path -to [get_pins -hier -regexp {tm_output/staged_sample_reg\[[0-9]+\]/CLR}]
# Paired mailbox reset; held data precedes its toggle by an extra destination
# cycle. Bound the fast (4ns) domain to 3ns, not the ADC mailbox's 20ns.
set_max_delay 3.000 -datapath_only -from [get_clocks clk_out1_clk_wiz_tc] -to [get_pins -hier -regexp {tm_transmitter/tm_cmd_mailbox/data_meta_reg\[[0-9]+\]/D}]
set_max_delay 20.000 -datapath_only -from [get_clocks clk_out1_clk_wiz_tm] -to [get_pins -hier -regexp {tm_transmitter/tm_done_mailbox/data_meta_reg\[[0-9]+\]/D}]
