connect
puts "=== ???? ==="
puts [targets]
targets -set -filter {name =~ "ARM*#0"}
stop
puts ""
puts "=== CPU ?? ==="
catch {puts "  PC = [rrd pc]"} e1
catch {puts "  CPSR = [rrd cpsr]"} e2
catch {puts "  LR = [rrd lr]"} e3
puts ""
puts "=== ???? ==="
puts "  OCM  0x00000000 (FSBL ?) : [mrd -value 0x00000000]"
puts "  OCM  0x00000040           : [mrd -value 0x00000040]"
puts "  ?? 0x00100000           : [mrd -value 0x00100000]"
puts "  ?? 0x003F0000           : [mrd -value 0x003F0000]"
puts "  ?? 0x003F0004           : [mrd -value 0x003F0004]"
puts ""
puts "=== 0x00000000 ?? 32 ?? ==="
for {set i 0} {$i < 32} {incr i 4} {
  puts [format "  +0x%02X : %08X" $i [mrd -value [expr {0x00000000 + $i}]]]
}
catch {con}
