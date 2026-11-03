connect
puts [targets]
targets -set -filter {name =~ "ARM*#0"}
foreach addr {0xE000B000 0xE000B004 0xE000B008 0xE000B018 0xE000B01C 0xE000C000 0xF800012C 0xF8000140 0xF8000144 0xF8000214 0xF8000740 0xF80007D0} {
    if {[catch {mrd $addr 1} result]} {puts "$addr ERROR $result"} else {puts $result}
}
disconnect
exit
