connect
targets -set -filter {name =~ "APU*"}
catch {rst -system}
after 2000
targets -set -filter {name =~ "Arm*#0"}
catch {con}
after 500
puts "JTAG_DONE"
