`timescale 1ns/1ps
module tb_tm_dac_config;
 reg clk=0,reset=1,allowed=0;
 always #20 clk=~clk;
 wire sdo,oe,cs,sclk,verified,finished;
 wire [31:0] diagnostic;
 tri1 bus;
 reg slave_oe=0,slave_bit=1;
 integer fault_mode=0,corrupt_address=-1,transactions=0;
 assign bus=oe ? sdo:1'bz;
 assign bus=slave_oe ? slave_bit:1'bz;
 assign bus=(fault_mode==2) ? 1'b0:1'bz;
 tm_dac_config #(.SPI_HALF_CYCLES(2),.CONFIG_TIMEOUT_CYCLES(10000)) dut(
  .clk25(clk),.reset(reset),.start_allowed(allowed),.sdi(bus),
  .sdo(sdo),.sdo_enable(oe),.cs_n(cs),.sclk(sclk),
  .verified(verified),.finished(finished),.diagnostic(diagnostic));
 reg [7:0] regs[0:127];
 reg [15:0] shift;
 reg [7:0] response,command;
 integer bits_seen=0,reads=0,writes=0,i,started;
 reg reading=0;
 always @(negedge cs) begin
  bits_seen=0;shift=0;slave_oe=0;reading=0;transactions=transactions+1;
 end
 always @(posedge cs) begin
  slave_oe=0;
  if(!reset && !finished && bits_seen!=16) $fatal(1,"transaction length %0d",bits_seen);
 end
 always @(posedge sclk) if(!cs) begin
  if(bits_seen<8 || !reading) begin
   if(!oe) $fatal(1,"master released command/write early");
   shift={shift[14:0],bus};
  end
  bits_seen=bits_seen+1;
  if(bits_seen==8) begin
   command=shift[7:0];reading=command[7];
   if(reading) begin
    reads=reads+1;
    response=regs[command[6:0]];
    if(command[6:0]==7'h18) response=(regs[7'h18][1]) ? 8'h07:8'h01;
    if(command[6:0]==7'h19) response=8'h0f;
    if(fault_mode==3 && command[6:0]==7'h18) response=0;
    if(fault_mode==4 && command[6:0]==7'h19) response=0;
    if(fault_mode==5 && command[6:0]==7'h18 && !regs[7'h18][1]) response=8'h05;
    if(command[6:0]==corrupt_address) response=response^8'hff;
    if(fault_mode==1) response=8'hff;
   end
  end
  if(bits_seen==16 && !reading) begin
   writes=writes+1;
   regs[shift[14:8]]=shift[7:0];
  end
 end
 always @(negedge sclk) if(!cs && reading && bits_seen>=8 && bits_seen<16) begin
  if(oe) $fatal(1,"SDIO turnaround overlap at bit %0d",bits_seen);
  slave_oe=(fault_mode!=1);
  slave_bit=response[15-bits_seen];
 end
 always @(posedge clk) if(slave_oe && oe) $fatal(1,"three-wire contention");
 task run_case(input integer mode,input integer address,input integer expect_reason);
  integer limit,old_tx;
  begin
   reset=1;allowed=0;fault_mode=mode;corrupt_address=address;
   for(i=0;i<128;i=i+1) regs[i]=0;
   regs[127]=8'h0c;regs[25]=8'h0f;
   repeat(5) @(negedge clk);
   reset=0;old_tx=transactions;
   repeat(12) @(negedge clk);
   if(transactions!=old_tx || verified || finished) $fatal(1,"premature start");
   allowed=1;limit=0;
   while(!finished && limit<11000) begin @(negedge clk);limit=limit+1;end
   if(!finished) $fatal(1,"unbounded configuration");
   if(diagnostic[31:28]!==expect_reason) $fatal(1,"reason=%h expected=%h step=%0d mode=%0d addr=%h",diagnostic,expect_reason,diagnostic[23:16],mode,address);
   if(verified !== (expect_reason==1)) $fatal(1,"verified on failure");
   old_tx=transactions;repeat(20) @(negedge clk);
   if(transactions!=old_tx) $fatal(1,"automatic retry");
  end
 endtask
 initial begin
  run_case(0,-1,1);
  if(writes!=26 || reads!=17) $fatal(1,"unexpected transaction counts writes=%0d reads=%0d",writes,reads);
  // Every critical gate rejects an incorrect read (not merely ID/format).
  run_case(0,'h7f,2);run_case(0,'h00,2);run_case(0,'h03,2);
  run_case(0,'h08,2);run_case(0,'h0a,2);run_case(0,'h10,2);
  run_case(0,'h11,2);run_case(0,'h16,2);run_case(0,'h1b,2);
  run_case(0,'h1c,2);run_case(0,'h1d,2);run_case(0,'h1e,2);run_case(0,'h17,2);
  run_case(0,'h01,2);
  run_case(1,-1,3); // disconnected read bus cannot finish alignment
  run_case(2,-1,5); // clamped write pin / echo fault
  run_case(3,-1,3); // FIFO acknowledgement never arrives
  run_case(4,-1,3); // FIFO level never becomes safe
  run_case(5,-1,3); // FIFO acknowledge does not deassert after request drops
  run_case(0,-1,1);
  allowed=0;repeat(3) @(negedge clk);
  if(verified || diagnostic[31:28]!=4) $fatal(1,"lost prerequisite did not invalidate verification");
  $display("TM_DAC_CONFIG_PASS critical read gates, FIFO deadline, echo fault, disconnected reads, turnaround, no retry");
  $finish;
 end
 initial begin #200000000; $fatal(1,"testbench watchdog");end
endmodule
