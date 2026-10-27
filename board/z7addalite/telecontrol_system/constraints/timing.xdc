create_clock -period 20.000 -name clk50m [get_ports clk50m]
create_clock -period 8.000 -name adc_dco -waveform {0.000 4.000} [get_ports adc_dco_p]
# Actual ADC125 DDR, UI4ns: data leads capture .4..1.0ns. Relative to previous
# opposite edge: 3.0..3.6ns, plus UNMEASURED +/-0.1ns PCB budget =2.9..3.7ns.
set_input_delay -clock adc_dco -min 2.900 [get_ports {adc_data_p[*]}]
set_input_delay -clock adc_dco -max 3.700 [get_ports {adc_data_p[*]}]
set_input_delay -clock adc_dco -clock_fall -min -add_delay 2.900 [get_ports {adc_data_p[*]}]
set_input_delay -clock adc_dco -clock_fall -max -add_delay 3.700 [get_ports {adc_data_p[*]}]
set_clock_uncertainty 0.100 [get_clocks adc_dco]
set_false_path -from [get_ports rst_n]
# Exact first-stage destinations only. No exception on ADC inputs or words.
set_false_path -to [get_pins -hier -regexp {.*(clock_done_sync_reg|delay_sync_reg|verified_sync_reg|config_busy_sync_reg|clock_fault_sync_reg|busy_sync_reg|stream_sync_reg|valid_sync_reg|heartbeat_sync_reg)\[0\]/D}]
# Mailbox controls alone are asynchronous first-stage false paths.
set_false_path -to [get_pins -hier -regexp {.*[a-z_]*mailbox/(toggle_sync_reg\[0\]|ack_sync_reg\[0\])/D}]
# Bundled payload is held until the returned ack. Two data stages precede the
# three-stage toggle and receiver publication. Bound every physical data path
# to 20ns, below the fastest destination period (32ns), so the extra control
# stage provides a full settling cycle. Never false-path the data bundle.
# Target the exact D pins so equivalent launch registers merged/renamed by
# synthesis (e.g. published_epoch instead of held_data) remain constrained.
set_max_delay 20.000 -datapath_only -from [get_clocks clk_out1_clk_wiz_tc] -to [get_pins -hier -regexp {config_mailbox/data_meta_reg\[[0-9]+\]/D}]
set_max_delay 20.000 -datapath_only -from [get_clocks clk_out1_clk_wiz_tc] -to [get_pins -hier -regexp {capture_path/command_mailbox/data_meta_reg\[[0-9]+\]/D}]
set_max_delay 20.000 -datapath_only -from [get_clocks clk_vec] -to [get_pins -hier -regexp {capture_path/event_mailbox/data_meta_reg\[[0-9]+\]/D}]
set_max_delay 20.000 -datapath_only -from [get_clocks clk_vec] -to [get_pins -hier -regexp {capture_path/training_mailbox/data_meta_reg\[[0-9]+\]/D}]
# Asynchronous assertion, synchronous release chains only; source data remains timed.
set_false_path -to [get_pins -hier -regexp {.*(reset25_sync_reg|reset200_sync_reg|ps_reset_sync_reg|vector_reset_sync_reg|capture_vector_reset_sync_reg)\[[0-9]+\]/PRE}]
# Slow mode-0 SPI launches from clk25; protocol edges/three-wire turnaround
# checked separately. Conservative 20ns pin budget vs40ns management cycle.
create_clock -period 40.000 -name spi_budget
set_output_delay -clock spi_budget -max 20.000 [get_ports {adc_sclk adc_sda adc_cs clk_sclk clk_sda clk_cs}]
set_output_delay -clock spi_budget -min 0.000 [get_ports {adc_sclk adc_sda adc_cs clk_sclk clk_sda clk_cs}]
set_input_delay -clock spi_budget -min 0.000 [get_ports adc_sda]
set_input_delay -clock spi_budget -max 20.000 [get_ports adc_sda]

set_property C_CLK_INPUT_FREQ_HZ 25000000 [get_debug_cores dbg_hub]
set_property C_ENABLE_CLK_DIVIDER false [get_debug_cores dbg_hub]
set_property C_USER_SCAN_CHAIN 1 [get_debug_cores dbg_hub]
connect_debug_port dbg_hub/clk [get_nets clk25]
