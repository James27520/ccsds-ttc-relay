`timescale 1ns/1ps
module tb_tm_dac_io;
 reg clk=0,reset=1; reg signed [15:0] sample=0;
 always #2 clk=~clk;
 wire dp,dn,fp,fn;wire [15:0] p,n;
 tm_dac_io dut(clk,reset,sample,dp,dn,fp,fn,p,n);
 reg [15:0] expected=0,old_expected=0;
 integer checks=0;
 always @(posedge clk) begin
  old_expected=expected;
  expected=reset?0:sample;
  #0.2;
  if($time>120)begin
   if(p!==(reset?16'd0:old_expected) || n!==~p || fp!==0 || fn!==1 || dp!==!reset || dn!==!dp)
    $fatal(1,"DDR rising mismatch p=%h expected=%h",p,old_expected);
   checks=checks+1;
  end
 end
 always @(negedge clk) begin
  #0.2;
  if($time>120)begin
   if(p!==0 || n!==16'hffff || dp!==0 || dn!==1)$fatal(1,"DDR Q lane not zero");
   checks=checks+1;
  end
 end
 initial begin
  #160;reset=0;
  for(integer k=0;k<40;k=k+1) begin
   @(negedge clk);#0.5;sample=(k&1)?-16'sd128:16'sd127;
  end
  @(negedge clk);#0.5;sample=0;repeat(3)@(posedge clk);
  #0.5;reset=1;#0.2;
  if(p!==0 || dp!==0)$fatal(1,"async reset failed");
  #12;reset=0;repeat(4)@(posedge clk);
  #1;$display("TM_DAC_IO_PASS checks=%0d signed_I_zero_Q_DCI_and_async_reset",checks);$finish;
 end
endmodule
