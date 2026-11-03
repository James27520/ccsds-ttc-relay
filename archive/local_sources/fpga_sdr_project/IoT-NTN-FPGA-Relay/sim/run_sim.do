#=============================================================================
# run_sim.do -- ModelSim ASE script for the relay datapath testbench
#   Usage (from E:\LDSDR_010\sim_relay):
#     vsim -c -do run_sim.do
#=============================================================================
if {[file exists work]} { vdel -all -lib work }
vlib work
vmap work work

set SRC "../zynq_dev_fmcomms3.srcs/sources_1/new"

vlog -quiet "$SRC/relay_sin_rom.v"
vlog -quiet "$SRC/relay_nco.v"
vlog -quiet "$SRC/relay_cmix.v"
vlog -quiet "$SRC/relay_cdc.v"
vlog -quiet "$SRC/relay_path.v"
vlog -quiet "$SRC/relay_dq.v"
vlog -quiet "tb_relay.v"

vsim -quiet -c tb_relay
run -all
quit -f
