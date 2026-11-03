setws E:/LDSDR_010/zynq_dev_fmcomms3.sdk
puts "=== ?? 1?? -bsp ==="
set r1 [catch {createapp -name fsbl_sd -hwproject relay_sd_hw -bsp fsbl_sd_bsp -proc ps7_cortexa9_0 -os standalone -lang c -app "Zynq FSBL"} e1]
puts "  catch=$r1  err=$e1"
if {$r1} {
  puts "=== ?? 2??? -bsp???????????==="
  set r2 [catch {createapp -name fsbl_sd -app "Zynq FSBL" -proc ps7_cortexa9_0 -hwproject relay_sd_hw -os standalone} e2]
  puts "  catch=$r2  err=$e2"
}
puts "=== ???? ==="
puts [projects]
