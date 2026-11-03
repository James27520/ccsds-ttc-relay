connect
targets -set -filter {name =~ "ARM*#0"}
proc sample {tag} {
    set m  [mrd -value 0x003F0000]
    set si [mrd -value 0x003F0004]
    set so [mrd -value 0x003F0008]
    set sc [mrd -value 0x003F000C]
    set rc [mrd -value 0x003F0010]
    set hb [mrd -value 0x003F0014]
    puts [format "%s  magic=0x%08X  in=%u  out=%u  clip=%u  rc=%d  hb=%u" $tag $m $si $so $sc $rc $hb]
    return [list $si $so]
}
set prev_in 0
set prev_out 0
for {set i 1} {$i <= 3} {incr i} {
    catch {con}
    after 2500
    catch {stop}
    set r [sample "read $i :"]
    if {$i > 1} {
        puts [format "           delta_in = %u   delta_out = %u   (2.5 s)" \
              [expr {[lindex $r 0] - $prev_in}] [expr {[lindex $r 1] - $prev_out}]]
    }
    set prev_in  [lindex $r 0]
    set prev_out [lindex $r 1]
}
catch {con}
puts "CPU resumed - the PL relay keeps running independently."
