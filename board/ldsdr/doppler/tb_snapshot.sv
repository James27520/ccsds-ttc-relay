`timescale 1ns/1ps
module tb_snapshot;
reg clk=0,dq=0,resetn=0;
always #5 clk=~clk;
always #4.069 dq=~dq;
reg [15:0] awaddr=0,araddr=0;
reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
wire awready,wready,bvalid,arready,rvalid;
wire [1:0] bresp,rresp;
reg [31:0] wdata=0;
wire [31:0] rdata;
reg [3:0] wstrb=15;
reg [1:0] phase=0;
reg [11:0] i1=0,i2=123;
wire [11:0] q1=~i1,q2=~i2;
wire v1=phase==0,v2=phase==2;
always @(negedge dq) begin
 phase<=phase+1'b1;
 if(v1) i1<=i1+1'b1;
 if(v2) i2<=i2+1'b1;
end
relay_iq_snapshot dut(.s_axi_aclk(clk),.s_axi_aresetn(resetn),
 .s_axi_awaddr(awaddr),.s_axi_awprot(3'b0),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
 .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
 .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
 .s_axi_araddr(araddr),.s_axi_arprot(3'b0),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
 .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
 .dq_clk(dq),.valid1(v1),.i1(i1),.q1(q1),.valid2(v2),.i2(i2),.q2(q2));
task write_req(input bit expect_error);
 begin
  // W arrives independently, before AW.
  @(negedge clk); wdata=1;wvalid=1;
  do @(posedge clk); while(!wready);
  @(negedge clk); wvalid=0;
  repeat(3) @(negedge clk);
  awaddr=8;awvalid=1;
  do @(posedge clk); while(!awready);
  @(negedge clk);awvalid=0;
  wait(bvalid);
  if((bresp!=0)!=expect_error) $fatal(1,"write response %d",bresp);
  @(negedge clk);bready=1;
  @(negedge clk);bready=0;
 end
endtask
task read_word(input [15:0] addr,output [31:0] data,input bit expect_error);
 begin
  @(negedge clk);araddr=addr;arvalid=1;
  do @(posedge clk);while(!arready);
  @(negedge clk);arvalid=0;
  wait(rvalid);data=rdata;
  if((rresp!=0)!=expect_error) $fatal(1,"read response addr=%h resp=%d",addr,rresp);
  repeat(3) begin @(negedge clk);if(!rvalid || data!==rdata) $fatal(1,"backpressure");end
  rready=1;@(negedge clk);rready=0;
 end
endtask
reg [31:0] data,first0,first1,last0,last1;
integer k,cycle;
initial begin
 #80;@(negedge clk);resetn=1;
 read_word(0,data,0);if(data!==32'h44505131) $fatal(1,"magic");
 read_word(16'h4000,data,1);
 for(cycle=0;cycle<2;cycle=cycle+1) begin
  write_req(0);write_req(1);
  do begin #2000;read_word(4,data,0);end while(data&1);
  read_word(16'h10,data,0);if(data!==cycle+1) $fatal(1,"sequence");
  read_word(16'h4000,first0,0);read_word(16'h8000,first1,0);
  for(k=0;k<4096;k=k+1) begin
   read_word(16'h4000+4*k,last0,0);read_word(16'h8000+4*k,last1,0);
   if(last0[11:0]!==((first0+k)&4095) || last1[11:0]!==((first1+k)&4095)) $fatal(1,"sample order %d",k);
   if(last0[27:16]!==~last0[11:0] || last1[27:16]!==~last1[11:0]) $fatal(1,"IQ packing");
  end
  #10000;read_word(16'h4000,data,0);if(data!==first0) $fatal(1,"snapshot overwritten");
 end
 @(negedge clk);resetn=0;repeat(5) @(negedge clk);resetn=1;
 read_word(4,data,0);if(data!=0) $fatal(1,"reset");
 $display("SNAPSHOT_PASS: independent AXI channels, two captures, both IQ banks, backpressure, frozen ownership, reset");
 $finish;
end
initial begin #10000000;$fatal(1,"timeout");end
endmodule
