connect
after 1500
puts "=== JTAG ??? ==="
catch { targets } e
puts "ERR: $e"
puts "=== jtag ??/?? ==="
catch { jtag targets } e2
puts "ERR2: $e2"
puts "DONE"
