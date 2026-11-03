connect
puts "=== ???? ==="
puts [targets]
targets -set -filter {name =~ "ARM*#0"}
puts "  PC = [rrd pc]"
puts "=== ?? CPU ==="
catch {con}
after 1000
puts "  ? con"
