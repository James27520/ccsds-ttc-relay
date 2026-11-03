connect
targets -set -filter {name =~ "APU*"}
catch {rst -system}
after 1500
puts "JTAG_RESET_DONE"
