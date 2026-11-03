puts "VIVADO_VERSION=[version -short]"
set part [get_parts -quiet xc7z010clg400-1]
puts "ZYNQ7010_PART=$part"
if {[llength $part] == 1} {
    create_project -in_memory -part xc7z010clg400-1
    puts "PS7_IP=[get_ipdefs -all -quiet xilinx.com:ip:processing_system7:*]"
    close_project
}
exit
