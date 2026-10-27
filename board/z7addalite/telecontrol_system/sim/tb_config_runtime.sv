`timescale 1ns/1ps
module tb_config_runtime;
 reg clk=0,reset=1,mode_start=0,mode_value=0;
 wire config_busy;wire [31:0] active_mode,config_epoch;
 wire clk_sclk,clk_sda,clk_cs,adc_sclk,adc_sda,adc_sda_enable,adc_cs;
 wire config_done,config_finished,diagnostic_toggle;
 wire [111:0] diagnostic;
 wire [6:0] config_index;
 tri1 sdio;
 reg slave_oe=0,slave_bit=0;
 reg [7:0] bank_a[0:255],bank_b[0:255],global_active[0:255];
 reg [7:0] shadow_a[0:255],shadow_b[0:255],global_shadow[0:255];
 reg [7:0] returned[0:9],response=0,selected=3;
 reg [23:0] adc_shift=0,clk_shift=0;
 integer adc_rises=0,adc_falls=0,clock_rises=0,clock_falls=0;
 integer read_count=0,adc_writes=0,clock_writes=0,case_number=0,checks=0;
 integer scenario=0,transfer_count=0,select_a_count=0,select_b_count=0;
 reg clock_125_written=0,adc_active=0,clock_active=0;
 reg command_read=0;
 reg [12:0] command_address=0;
 reg [111:0] expected_diag,saved_diag;
 integer expected_error,expected_passed,waits,j;
 reg [7:0] expected_marker;
 reg held_toggle;

 always #20 clk=~clk;
 assign sdio=adc_sda_enable?adc_sda:1'bz;
 assign sdio=slave_oe?slave_bit:1'bz;
 tc_adc_config #(.STARTUP_CYCLES(2),.PLL_WAIT_CYCLES(5),
  .SPI_HALF_CYCLES(2),.TIMEOUT_CYCLES(20000)) dut(
  .clk25(clk),.reset(reset),.mode_start(mode_start),.mode_value(mode_value),.adc_sdi(sdio),
  .clk_sclk(clk_sclk),.clk_sda(clk_sda),.clk_cs(clk_cs),
  .adc_sclk(adc_sclk),.adc_sdo(adc_sda),.adc_sdo_enable(adc_sda_enable),.adc_cs(adc_cs),
  .config_busy(config_busy),.config_verified(config_done),.startup_finished(config_finished),
  .active_mode(active_mode),.config_epoch(config_epoch),.diagnostic(diagnostic),.result_toggle(diagnostic_toggle));
 assign config_index=dut.boot_index;

 task check(input bit condition,input string explanation);
 begin checks=checks+1;if(!condition)$fatal(1,"case%0d at%0t: %s",scenario,$time,explanation);end
 endtask
 function automatic bit local_register(input integer address);
  local_register=(address==8 || address==13 || address==16 || address==20);
 endfunction
 task chip_reset;
  integer a;
 begin
  selected=3;
  for(a=0;a<256;a=a+1)begin
   bank_a[a]=0;bank_b[a]=0;global_active[a]=0;
   shadow_a[a]=0;shadow_b[a]=0;global_shadow[a]=0;
  end
  bank_a[20]=8'h05;bank_b[20]=8'h05;shadow_a[20]=8'h05;shadow_b[20]=8'h05;
  global_active[1]=8'h82;global_shadow[1]=8'h82;
  global_active[0]=8'h18;global_shadow[0]=8'h18;
 end
 endtask
 task chip_write(input [12:0] address,input [7:0] value);
  integer a;
 begin
  check(address<256,"ADC address within modeled map");
  if(config_finished)check(address==5 || address==13 || address==255,"runtime only index/test/transfer writes");
  if(address==0) begin
   check(selected===8'h03,"AD9643 p34: both channels selected before every00 write");
   if(value & 8'h24) chip_reset();
   else begin global_active[0]=value;global_shadow[0]=value;end
  end else if(address==5) begin
   selected=value;
   if(value==1)select_a_count=select_a_count+1;
   if(value==2)select_b_count=select_b_count+1;
  end else if(address==255 && value[0])begin
   transfer_count=transfer_count+1;
   for(a=8;a<=32;a=a+1)begin
    bank_a[a]=shadow_a[a];bank_b[a]=shadow_b[a];global_active[a]=global_shadow[a];
   end
  end else if(local_register(address))begin
   if(selected[0])shadow_a[address]=value;
   if(selected[1])shadow_b[address]=value;
  end else global_shadow[address]=value;
 end
 endtask
 function automatic [7:0] chip_read(input [12:0] address);
 begin
  if(address==5)chip_read=selected;
  else if(local_register(address))begin
   if(selected[0])chip_read=bank_a[address]; // Per p31 both-selected read returns A.
   else if(selected[1])chip_read=bank_b[address];
   else chip_read=8'hxx;
  end else chip_read=global_active[address];
 end
 endfunction
 function automatic [7:0] corrupt(input [7:0] normal,input integer ordinal);
 begin
  corrupt=normal;
  if(scenario==ordinal)begin
   case(ordinal)
    1,2,4,5,8,10:corrupt=normal^8'h01;
    3,9:corrupt=normal^8'h10;
    6,7:corrupt=normal^8'h80;
   endcase
  end
  if(scenario==11)corrupt=8'h00;
  if(scenario==12)corrupt=8'hff;
  if(scenario==15 && ordinal==4)corrupt=normal|8'h80;
  if(scenario==16 && ordinal==10)corrupt=normal|8'h80;
  if(scenario==18)corrupt=8'hxx;
 end
 endfunction

 always @(adc_sda_enable or slave_oe)
  if(adc_sda_enable && slave_oe)$fatal(1,"case%0d SDIO contention",scenario);

 always @(negedge clk_cs) if(!reset)begin
  check(!config_finished,"runtime never selects AD9516");
  clock_active=1;clk_shift=0;clock_rises=0;clock_falls=0;
  check(adc_cs,"clock-chip transaction cannot select ADC");
 end
 always @(posedge clk_sclk) if(clock_active && !reset)begin
  check(!clk_cs && adc_cs,"clock SCLK confined to clock-chip CS");
  clk_shift={clk_shift[22:0],clk_sda};clock_rises=clock_rises+1;
 end
 always @(negedge clk_sclk) if(clock_active && !reset && !clk_cs)clock_falls=clock_falls+1;
 always @(posedge clk_cs) if(clock_active)begin
  if(!reset)begin
   check(clock_rises==24 && clock_falls==24,"clock-chip exact24 clocks");
   check(!clk_shift[23],$sformatf("clock-chip writes only observed=%06h index=%0d",clk_shift,config_index));
   if(clk_shift[23:8]==16'h0199)begin
    check(clk_shift[7:0]===8'h33,"AD9516 channel divider 0199=33 for125 candidate");
    clock_125_written=1;
   end
   clock_writes=clock_writes+1;
  end
  clock_active=0;
 end

 always @(negedge adc_cs)if(!reset)begin
  adc_active=1;adc_shift=0;adc_rises=0;adc_falls=0;command_read=0;command_address=0;
  check(clk_cs,"ADC transaction cannot select clock chip");
 end
 always @(posedge adc_sclk)if(adc_active && !reset)begin
  adc_rises=adc_rises+1;adc_shift={adc_shift[22:0],sdio};
  check(!adc_cs && clk_cs,"ADC SCLK confined to ADC CS");
  if(adc_rises<=16)check(adc_sda_enable && !slave_oe,"master owns ADC command");
  if(adc_rises==16)begin
   command_read=adc_shift[15];command_address=adc_shift[12:0];
   check(adc_shift[14:13]===2'b00,"single-byte command W1/W0 zero");
   if(command_read)begin
    read_count=read_count+1;
    check(read_count<=10,"no extra reads");
    response=corrupt(chip_read(command_address),read_count);
    if(scenario==17)response=8'hff; // no device: pulled-high resolved SDIO
    returned[read_count-1]=response;
   end
  end
  if(adc_rises>16)begin
   if(command_read)check(!adc_sda_enable,"master high-Z throughout read data");
   else check(adc_sda_enable && !slave_oe,"master owns ADC write data");
  end
 end
 always @(negedge adc_sclk)if(adc_active && !reset && !adc_cs)begin
  adc_falls=adc_falls+1;
  if(command_read && adc_rises>=16 && adc_rises<24)begin
   check(!adc_sda_enable,"released before slave data falling edge");
   #10;slave_bit=response[23-adc_rises];slave_oe=(scenario!=17);
  end
 end
 always @(posedge adc_cs)if(adc_active)begin
  if(!reset)begin
   check(adc_rises==24 && adc_falls==24,"ADC exact24 clocks");
   if(!command_read)begin
    chip_write(adc_shift[20:8],adc_shift[7:0]);adc_writes=adc_writes+1;
   end else check(!adc_sda_enable,"read remains high-Z at CS high");
  end
  adc_active=0;#20;slave_oe=0;
 end


 integer previous_writes,previous_transfer,runtime_cases=0;
 reg [31:0] previous_epoch;
 reg old_toggle;
 task runtime_case(input integer number,input bit test_mode);
 begin
  @(negedge clk);scenario=number;read_count=0;previous_writes=adc_writes;
  previous_transfer=transfer_count;previous_epoch=config_epoch;old_toggle=diagnostic_toggle;
  for(j=0;j<10;j=j+1)returned[j]=0;
  mode_value=test_mode;mode_start=1;
  @(negedge clk);mode_start=0;
  check(config_busy && !config_done && config_finished,"runtime invalidates mode but keeps startup finished");
  if(number==13)force dut.done=1'b0;
  // Requests while busy must not modify the accepted mode or restart clocks.
  repeat(8)@(negedge clk);mode_value=!test_mode;mode_start=1;
  repeat(2)@(negedge clk);mode_start=0;
  waits=0;
  while(config_busy && waits<22000)begin @(negedge clk);waits=waits+1;end
  check(!config_busy && config_finished,"bounded completion; sticky startup");
  if(number==0)begin expected_error=0;expected_passed=10;end
  else if(number<=10)begin expected_error=number;expected_passed=number-1;end
  else if(number==11 || number==12 || number==17 || number==18)begin expected_error=1;expected_passed=0;end
  else if(number==13)begin
   expected_error=11;expected_passed=0;
   for(j=0;j<10;j=j+1)returned[j]=0;
  end else if(number==15)begin expected_error=4;expected_passed=3;end
  else begin expected_error=10;expected_passed=9;end
  expected_marker=(number==0)?8'ha1:8'he1;
  expected_diag={8'h7d,expected_marker,8'(expected_passed),8'(expected_error),
   returned[7],returned[1],returned[6],returned[5],returned[4],returned[9],returned[3],returned[8],returned[2],returned[0]};
  check(diagnostic===expected_diag,"published diagnostic uses actual independent read replies");
  check(config_done===(number==0),"failure cannot set verified");
  check(active_mode==((number==0?32'h80000000:32'h0)|32'(test_mode)),"mode remains latched; validity reflects checks");
  check(config_epoch==previous_epoch+1 && diagnostic_toggle!=old_toggle,"success AND failure publish new epoch/toggle");
  check(clock_writes==76,"no runtime clock programming");
  if(number==0)begin
   check(read_count==10 && adc_writes-previous_writes==8,"18 transactions/10 checks per runtime switch");
   check(transfer_count==previous_transfer+1,"transfer both channel shadow test settings");
   check(bank_a[13]==(test_mode?6:0) && bank_b[13]==(test_mode?4:0),"committed modes match request");
   check(bank_a[20]==5 && bank_b[20]==5 && global_active[11]==0 && global_active[22]==0 && global_active[23]==0,"format/clock state untouched");
   check(selected==1,"restore index A");
  end
  saved_diag=diagnostic;held_toggle=diagnostic_toggle;
  repeat(30)begin
   @(negedge clk);
   check(diagnostic===saved_diag && diagnostic_toggle==held_toggle && config_finished && !config_busy,"stable completed publication");
  end
  release dut.done;
  runtime_cases=runtime_cases+1;
  $display("RUNTIME_CASE_PASS n=%0d mode=%0d epoch=%0d error=%0d",number,test_mode,config_epoch,expected_error);
 end
 endtask
 initial begin
  chip_reset();repeat(4)@(negedge clk);reset=0;
  waits=0;while(!config_finished && waits<22000)begin @(negedge clk);waits=waits+1;end
  check(config_finished && config_done && !config_busy && config_epoch==1,"boot succeeds exactly once");
  check(diagnostic===112'h7da10a0002010000000406050582,"PN9 boot readback");
  runtime_case(0,0);runtime_case(0,1);
  for(case_number=1;case_number<=13;case_number=case_number+1)begin
   runtime_case(case_number,case_number%2);
   runtime_case(0,1); // Recover via mode-only configuration, never reconfigure clocks.
  end
  for(case_number=15;case_number<=18;case_number=case_number+1)begin
   runtime_case(case_number,0);runtime_case(0,1);
  end
  // Epoch wrap skips zero; value is a simulation deposit, not a software API.
  @(negedge clk);dut.config_epoch=32'hfffffffe;
  runtime_case(0,0);
  @(negedge clk);read_count=0;mode_value=1;mode_start=1;
  @(negedge clk);mode_start=0;wait(config_busy);wait(!config_busy);@(negedge clk);
  check(config_epoch==1 && config_done,"publication epoch skips zero on wrap");
  // Mid-transfer reset reruns full boot with no retained validity/publication.
  @(negedge clk);read_count=0;mode_value=0;mode_start=1;
  @(negedge clk);mode_start=0;repeat(20)@(negedge clk);reset=1;
  repeat(5)@(negedge clk);check(!config_finished && !config_done && config_epoch==0,"reset clears source validity");
  scenario=0;read_count=0;clock_writes=0;adc_writes=0;chip_reset();reset=0;
  wait(config_finished);@(negedge clk);check(config_done && config_epoch==1,"boot restarts after interrupted runtime");
  // A failed initial boot cannot be promoted to ready by mode-only writes.
  @(negedge clk);reset=1;repeat(5)@(negedge clk);
  scenario=12;read_count=0;clock_writes=0;adc_writes=0;chip_reset();reset=0;
  wait(config_finished);@(negedge clk);
  check(!config_done && config_epoch==1 && !active_mode[31],"failed boot publication");
  scenario=0;previous_writes=adc_writes;mode_value=0;mode_start=1;
  @(negedge clk);mode_start=0;wait(!config_busy);@(negedge clk);
  check(!config_done && config_epoch==2 && diagnostic[87:80]==13,"failed boot requires full restart");
  check(adc_writes==previous_writes && clock_writes==76,"mode-only retry cannot mask incomplete initial configuration");
  $display("CONFIG_RUNTIME_PASS cases=%0d checks=%0d contention=0",runtime_cases,checks);$finish;
 end
 initial begin #100000000;$fatal(1,"runtime BFM global timeout");end
endmodule
