connect
puts "=== ?? ==="
puts [targets]
targets -set -filter {name =~ "ARM*#0"}
puts "=== ??????? ==="
catch {rst -system}
after 2000
puts "  ???"
