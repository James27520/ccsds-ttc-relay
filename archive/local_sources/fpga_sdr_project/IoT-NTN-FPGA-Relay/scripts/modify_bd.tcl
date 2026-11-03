#=============================================================================
# modify_bd.tcl -- insert relay_dq into design_1 and drive the AD9361 DAC port
#                  from it instead of from dds_dq_0.
#
# HOW TO RUN (preferred: let build_pl.tcl call it, so the nested axi_ctrl IP
#             is refreshed first - see the note in step 4 below)
#   Vivado -> Tools -> Run Tcl Script... -> pick this file
#
# SAFE TO RE-RUN: every connection is made through safe_connect, which is a
# no-op when the two pins already share a net.
#
# WHAT IT DOES
#   1. switch the project to automatic compile order (required for module refs)
#   2. add the relay RTL to sources_1
#   3. open design_1
#   4. disconnect dds_dq_0 from ad9361_phy_0's DAC port
#   5. create relay_dq_0  (module reference, no IP packaging needed)
#   6. wire ADC -> relay -> DAC, clock, reset, phy_mode
#   7. connect the relay control/status ports to axi_ctrl when the patched IP
#      is present, otherwise tie them to xlconstant defaults
#   8. re-point the existing ILA probes at the relayed DAC signals
#   9. validate and save
#=============================================================================

set PROJ_DIR  "E:/LDSDR_010"
set SRC_DIR   "$PROJ_DIR/zynq_dev_fmcomms3.srcs/sources_1/new"
set BD_NAME   "design_1"

proc banner {m} { puts "\n---- $m" }

#-----------------------------------------------------------------------------
# helper: connect two pins unless they are already on the same net
#-----------------------------------------------------------------------------
proc safe_connect {a b} {
    set pa [get_bd_pins -quiet $a]
    set pb [get_bd_pins -quiet $b]
    if {$pa eq "" || $pb eq ""} {
        puts "   SKIP (missing pin) : $a <-> $b"
        return 0
    }
    set na [get_bd_nets -quiet -of_objects $pa]
    set nb [get_bd_nets -quiet -of_objects $pb]
    if {($na ne "") && ($na eq $nb)} {
        puts "   ok, already on $na"
        return 0
    }
    if {[catch {connect_bd_net $pa $pb} e]} {
        puts "   !! connect failed : $a <-> $b : $e"
        return 0
    }
    puts "   connected : $a <-> $b"
    return 1
}

#-----------------------------------------------------------------------------
# 0. sanity
#-----------------------------------------------------------------------------
if {[catch {current_project} p]} {
    error "Open the project E:/LDSDR_010/zynq_dev_fmcomms3.xpr first."
}
puts "== project: [current_project]"

#-----------------------------------------------------------------------------
# 1. automatic compile order  (module references need it)
#-----------------------------------------------------------------------------
set mgmt [get_property source_mgmt_mode [current_project]]
puts "== source_mgmt_mode = $mgmt"
if {$mgmt ne "All"} {
    set_property source_mgmt_mode All [current_project]
    puts "   switched source_mgmt_mode -> All"
}

#-----------------------------------------------------------------------------
# 2. add the relay RTL sources
#-----------------------------------------------------------------------------
set relay_files [list \
    "$SRC_DIR/relay_sin_rom.v" \
    "$SRC_DIR/relay_nco.v"     \
    "$SRC_DIR/relay_cmix.v"    \
    "$SRC_DIR/relay_cdc.v"     \
    "$SRC_DIR/relay_path.v"    \
    "$SRC_DIR/relay_dq.v"      ]

foreach f $relay_files {
    if {![file exists $f]} { error "missing source file: $f" }
    if {[llength [get_files -quiet $f]] == 0} {
        add_files -norecurse -fileset sources_1 $f
        puts "   added [file tail $f]"
    } else {
        puts "   already in project: [file tail $f]"
    }
}
update_compile_order -fileset sources_1
puts "   top module: [get_property TOP [current_fileset]]"

#-----------------------------------------------------------------------------
# 3. open the block design
#-----------------------------------------------------------------------------
if {[current_bd_design -quiet] eq ""} {
    open_bd_design [get_files ${BD_NAME}.bd]
}
puts "== block design: [current_bd_design]"

#-----------------------------------------------------------------------------
# 4. NOTE on ordering
#    The BD cell's port list comes from the GENERATED IP products, not from
#    the .bd file.  If you run this script standalone on a project where
#    repo/axi_ctrl was just patched, first do:
#        update_ip_catalog -rebuild
#        reset_target    all [get_files design_1.bd]
#        generate_target all [get_files design_1.bd]
#    otherwise tie_or_connect below will not see the new registers and will
#    fall back to xlconstant tie-offs.
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# 5. disconnect dds_dq_0 from the DAC port of ad9361_phy_0
#    (whatever is currently driving it - dds_dq_0 on the first run,
#     relay_dq_0 on a re-run)
#-----------------------------------------------------------------------------
foreach pin {dac_data_d1 dac_data_q1 dac_data_d2 dac_data_q2 dac_valid} {
    foreach n [get_bd_nets -quiet -of_objects [get_bd_pins -quiet ad9361_phy_0/$pin]] {
        if {$n ne ""} {
            puts "   removing net $n from ad9361_phy_0/$pin"
            catch {delete_bd_objs $n}
        }
    }
}

#-----------------------------------------------------------------------------
# 6. create relay_dq_0 as a module reference
#-----------------------------------------------------------------------------
if {[llength [get_bd_cells -quiet relay_dq_0]] == 0} {
    create_bd_cell -type module -reference relay_dq relay_dq_0
    puts "   created relay_dq_0"
} else {
    puts "   relay_dq_0 already exists"
}
catch {set_property -dict [list CONFIG.SNAP_PERIOD {4096}] [get_bd_cells relay_dq_0]}

#-----------------------------------------------------------------------------
# 7. clock / reset / phy_mode
#-----------------------------------------------------------------------------
banner "clock, reset, phy_mode"
safe_connect ad9361_phy_0/data_clk               relay_dq_0/dq_data_clk
safe_connect proc_sys_reset_0/peripheral_aresetn relay_dq_0/rst_n
safe_connect processing_system7_0/FCLK_CLK0      relay_dq_0/raxi_clk
safe_connect axi_ctrl_v1_0_0/phy_mode            relay_dq_0/phy_mode

#-----------------------------------------------------------------------------
# 8. ADC -> relay
#-----------------------------------------------------------------------------
banner "ADC side"
foreach p {adc_d1q1_valid adc_data_d1 adc_data_q1 adc_d2q2_valid adc_data_d2 adc_data_q2} {
    safe_connect ad9361_phy_0/$p relay_dq_0/$p
}

#-----------------------------------------------------------------------------
# 9. relay -> DAC
#-----------------------------------------------------------------------------
banner "DAC side"
foreach p {dac_valid dac_data_d1 dac_data_q1 dac_data_d2 dac_data_q2} {
    safe_connect relay_dq_0/$p ad9361_phy_0/$p
}

#-----------------------------------------------------------------------------
# 10. control / status
#     If the patched axi_ctrl IP is present the relay is fully software
#     controlled.  Otherwise safe defaults are tied off so the relay still
#     works as a plain 1:1 bent pipe right after power-up.
#-----------------------------------------------------------------------------
banner "control / status"

proc tie_or_connect {rl_port ip_port width defval} {
    set ip_pin [get_bd_pins -quiet axi_ctrl_v1_0_0/$ip_port]
    set rl_pin [get_bd_pins -quiet relay_dq_0/$rl_port]
    set cname  "const_$rl_port"

    if {$ip_pin ne ""} {
        if {[llength [get_bd_cells -quiet $cname]] > 0} {
            puts "   removing old $cname"
            catch {delete_bd_objs [get_bd_cells $cname]}
        }
        foreach n [get_bd_nets -quiet -of_objects $rl_pin] {
            if {$n ne ""} { catch {delete_bd_objs $n} }
        }
        safe_connect axi_ctrl_v1_0_0/$ip_port relay_dq_0/$rl_port
    } else {
        if {[llength [get_bd_cells -quiet $cname]] == 0} {
            create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 $cname
        }
        set_property -dict [list CONFIG.CONST_WIDTH $width CONFIG.CONST_VAL $defval] \
            [get_bd_cells $cname]
        safe_connect $cname/dout relay_dq_0/$rl_port
        puts "   relay_dq_0/$rl_port <- xlconstant $defval (width $width)"
    }
}

# NOTE the names differ on purpose:
#   relay_dq_0/ctrl_*   is what the relay module calls them
#   axi_ctrl_v1_0_0/relay_*  is what the patched register file calls them
# defaults: relay mode, no DC block, unity gain, no frequency translation
tie_or_connect ctrl_mode     relay_mode      2  "1"   ;# 0=bypass 1=relay 2=mute 3=duc_only
tie_or_connect ctrl_dc_en    relay_dc_en     1  "0"
tie_or_connect ctrl_gain     relay_gain     12  "800" ;# Q1.11, 0x800 = 1.0
tie_or_connect ctrl_ddc_freq relay_ddc_freq 32  "0"
tie_or_connect ctrl_duc_freq relay_duc_freq 32  "0"

foreach p {status_sample_cnt status_clip_cnt status_out_cnt} {
    if {[get_bd_pins -quiet axi_ctrl_v1_0_0/$p] ne ""} {
        safe_connect relay_dq_0/$p axi_ctrl_v1_0_0/$p
    } else {
        puts "   NOTE: axi_ctrl_v1_0_0/$p not present - status counters unreadable"
    }
}

#-----------------------------------------------------------------------------
# 11. re-point the ILA probes at the relayed signals
#-----------------------------------------------------------------------------
banner "ILA probes"
foreach {probe pin} {probe0 dac_valid  probe8 dac_data_d1  probe9 dac_data_q1 \
                     probe10 dac_data_d2  probe11 dac_data_q2} {
    set ila_pin [get_bd_pins -quiet ila_0/$probe]
    if {$ila_pin eq ""} { continue }
    set cur [get_bd_nets -quiet -of_objects $ila_pin]
    set want [get_bd_nets -quiet -of_objects [get_bd_pins -quiet relay_dq_0/$pin]]
    if {($cur ne "") && ($cur eq $want)} {
        puts "   ila_0/$probe already on relay_dq_0/$pin"
        continue
    }
    foreach n $cur { if {$n ne ""} { catch {delete_bd_objs $n} } }
    safe_connect relay_dq_0/$pin ila_0/$probe
}

#-----------------------------------------------------------------------------
# 12. validate + save
#-----------------------------------------------------------------------------
banner "validate and save"
regenerate_bd_layout
if {[catch {validate_bd_design} e]} {
    puts "!! validate_bd_design reported: $e"
}
save_bd_design
puts "== design_1 updated and saved"
