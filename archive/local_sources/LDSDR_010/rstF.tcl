connect
after 1000
targets -set -filter {name =~ "APU*"}
catch {rst -system}
after 2500
targets -set -filter {name =~ "ARM*#0"}
catch {con}
after 500
puts "JTAG_RESET_OK"
