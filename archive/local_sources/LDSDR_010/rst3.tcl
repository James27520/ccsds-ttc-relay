connect
targets -set -filter {name =~ "APU*"}
catch {rst -system}
after 1500
puts "RESET_OK"
