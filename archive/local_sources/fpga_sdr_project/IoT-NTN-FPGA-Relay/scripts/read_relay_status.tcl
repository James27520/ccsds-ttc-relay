#=============================================================================
# read_relay_status.tcl -- read the relay registers over JTAG
#   xsct.bat E:/LDSDR_010/read_relay_status.tcl
#
# The PL relay keeps running while the CPU is halted, so the counters keep
# counting between the two reads - that is the "no sample loss" evidence.
#=============================================================================
set BASE 0x43C00000

proc rd {off} {
    return [expr {[mrd -value [expr {$::BASE + $off}]] & 0xFFFFFFFF}]
}

connect
targets -set -filter {name =~ "ARM*#0"}
stop

puts "\n========== relay registers =========="
puts [format "  0x%02X relay_mode      = %u" 0x10 [rd 0x10]]
puts [format "  0x%02X relay_ddc_freq  = 0x%08X" 0x14 [rd 0x14]]
puts [format "  0x%02X relay_duc_freq  = 0x%08X" 0x18 [rd 0x18]]
puts [format "  0x%02X relay_gain/dcen = 0x%08X" 0x1C [rd 0x1C]]
puts [format "  0x%02X phy_mode        = %u" 0x0C [rd 0x0C]]
puts [format "  0x%02X idelay_en       = 0x%02X" 0x00 [rd 0x00]]
puts [format "  0x%02X idelay_tap      = %u" 0x04 [rd 0x04]]

puts "\n========== counters, first read =========="
set s1 [rd 0x20]
set c1 [rd 0x24]
set o1 [rd 0x28]
puts [format "  status_sample_cnt = %u" $s1]
puts [format "  status_clip_cnt   = %u" $c1]
puts [format "  status_out_cnt    = %u" $o1]

after 3000

puts "\n========== counters, second read (3 s later) =========="
set s2 [rd 0x20]
set c2 [rd 0x24]
set o2 [rd 0x28]
puts [format "  status_sample_cnt = %u" $s2]
puts [format "  status_clip_cnt   = %u" $c2]
puts [format "  status_out_cnt    = %u" $o2]

puts "\n========== verdict =========="
puts [format "  delta sample = %u" [expr {$s2 - $s1}]]
puts [format "  delta out    = %u" [expr {$o2 - $o1}]]
if {$s2 == $s1} {
    puts "  !! NO SAMPLES ARRIVING  - check the AD9361 RX input / PHY mode"
} elseif {$o2 == $o1} {
    puts "  !! ADC running but no DAC output - check relay_mode"
} else {
    puts "  RELAY IS RUNNING: ADC samples are being relayed to the DAC"
}
if {$c2 > 0} {
    puts [format "  NOTE: %u saturation events - digital gain is too high" $c2]
}

con
puts "\nCPU resumed."
