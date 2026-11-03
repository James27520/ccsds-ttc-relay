#=============================================================================
# dbg_bd_pins.tcl -- 只做一件事：看 BD 里 relay_dq_0 和 axi_ctrl 单元的实际端口
#   vivado.bat -mode batch -source E:/LDSDR_010/dbg_bd_pins.tcl -log E:/LDSDR_010/dbg.log
#=============================================================================
set PROJ "E:/LDSDR_010/zynq_dev_fmcomms3.xpr"
proc banner {m} { puts "\n========== $m ==========" }

banner "open"
open_project $PROJ
update_ip_catalog -rebuild

set bdf [get_files -quiet design_1.bd]
banner "BD 文件"
puts "  $bdf"

banner "1. relay_dq.v 是否在工程里、内容是不是新版"
foreach f [get_files -quiet *relay_dq.v] {
    set fh [open $f r]; set d [read $fh]; close $fh
    puts "  $f"
    puts "     ctrl_mode2 存在 = [string match {*ctrl_mode2*} $d]"
}
puts "  sources_1 里所有匹配 relay 的文件:"
foreach f [get_files -quiet *relay*] { puts "     $f" }

banner "2. 打开 BD，看 relay_dq_0 现有端口"
open_bd_design $bdf
set cell [get_bd_cells -quiet relay_dq_0]
if {$cell eq ""} {
    puts "  relay_dq_0 不存在"
} else {
    puts "  relay_dq_0 pins:"
    foreach p [lsort [get_bd_pins -quiet -of_objects $cell]] {
        puts "     [file tail $p]"
    }
}

banner "3. 删掉重建，再看一次"
if {$cell ne ""} { delete_bd_objs $cell }
create_bd_cell -type module -reference relay_dq relay_dq_0
puts "  重建后 pins:"
foreach p [lsort [get_bd_pins -quiet -of_objects [get_bd_cells relay_dq_0]]] {
    puts "     [file tail $p]"
}

banner "4. axi_ctrl 单元端口（找 relay_mode2）"
set ac [get_bd_cells -quiet axi_ctrl_v1_0_0]
if {$ac eq ""} {
    puts "  axi_ctrl_v1_0_0 不存在"
} else {
    foreach p [lsort [get_bd_pins -quiet -of_objects $ac]] {
        set n [file tail $p]
        if {[string match "*relay*" $n] || [string match "*status*" $n]} { puts "     $n" }
    }
}

banner "5. VLNV / IP 版本"
foreach ip [get_ips -quiet] {
    puts "  [get_property IPDEF $ip]   ($ip)"
}

puts "\nDBG DONE"
