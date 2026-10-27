`timescale 1ns/1ps
module tb_axil;
 `include "capture_abi.vh"
 reg clk=0;always #20 clk=~clk;
 reg resetn=0;
 reg [31:0] awaddr=0,wdata=0,araddr=0;
 reg [3:0] wstrb=0;
 reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
 wire awready,wready,bvalid,arready,rvalid;
 wire [1:0] bresp,rresp;
 wire [31:0] rdata;
 wire wr_en,rd_en,wr_error,rd_error;
 wire [31:0] wr_addr,wr_data,rd_addr,rd_data;
 wire [3:0] wr_strb;
 reg [31:0] ctrl_value=0;
 integer accepted_writes=0,checks=0;
 reg capture_we=0;reg [15:0] capture_address=0;reg [31:0] capture_data=0;
 wire [31:0] ram_rd_data;wire ram_rd_error,ram_wr_error;
 wire is_ram=rd_addr>=TC_BRAM_BASE && rd_addr<TC_BRAM_BASE+TC_BRAM_RANGE;
 assign wr_error=(wr_addr!=TC_CTRL_BASE+TC_REG_REQUEST_EPOCH || wr_strb!=15);
 assign rd_data=is_ram?ram_rd_data:ctrl_value;
 assign rd_error=is_ram?ram_rd_error:(rd_addr!=TC_CTRL_BASE+TC_REG_REQUEST_EPOCH);
 always @(posedge clk)if(resetn && wr_en && !wr_error)begin ctrl_value<=wr_data;accepted_writes<=accepted_writes+1;end
 tc_axil_frontend dut(.clk(clk),.resetn(resetn),
 .s_axi_awaddr(awaddr),.s_axi_awprot(3'd0),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
 .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
 .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
 .s_axi_araddr(araddr),.s_axi_arprot(3'd0),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
 .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready),
 .wr_en(wr_en),.wr_addr(wr_addr),.wr_data(wr_data),.wr_strb(wr_strb),.wr_error(wr_error),
 .rd_en(rd_en),.rd_addr(rd_addr),.rd_data(rd_data),.rd_error(rd_error));
 tc_snapshot_ram ram(.clk(clk),.resetn(resetn),.capture_we(capture_we),
 .capture_word_address(capture_address),.capture_data(capture_data),
 .rd_en(rd_en),.rd_addr(rd_addr),.rd_data(ram_rd_data),.rd_error(ram_rd_error),.wr_error(ram_wr_error));
 task automatic check(input bit okay,input string msg);
  begin checks=checks+1;if(!okay)$fatal(1,"CHECK_FAIL %s at %t",msg,$time);end
 endtask
 task automatic send_aw(input [31:0] address,input integer delay_cycles);
  begin
   repeat(delay_cycles)@(posedge clk);
   @(negedge clk);awaddr=address;awvalid=1;
   do @(posedge clk);while(!awready);
   @(negedge clk);awvalid=0;
  end
 endtask
 task automatic send_w(input [31:0] data,input [3:0] strobes,input integer delay_cycles);
  begin
   repeat(delay_cycles)@(posedge clk);
   @(negedge clk);wdata=data;wstrb=strobes;wvalid=1;
   do @(posedge clk);while(!wready);
   @(negedge clk);wvalid=0;
  end
 endtask
 task automatic write_word(input [31:0] address,input [31:0] data,input [3:0] strobes,
   input integer awdelay,input integer wdelay,input integer hold_response,input [1:0] expected);
  integer k,baseline;
  begin
   baseline=accepted_writes;
   fork send_aw(address,awdelay);send_w(data,strobes,wdelay);join
   while(!bvalid)begin @(posedge clk);#1;end
   check(bresp===expected,"write response");
   for(k=0;k<hold_response;k=k+1)begin
    @(posedge clk);#1;check(bvalid && bresp===expected,"B stable under backpressure");
    check(!awready && !wready,"no extra write while B stalled");
   end
   check(accepted_writes==baseline+(expected==0),"write commits exactly once");
   @(negedge clk);bready=1;@(posedge clk);@(negedge clk);bready=0;
  end
 endtask
 task automatic read_word(input [31:0] address,input [31:0] expected_data,input [1:0] expected_resp,input integer hold_response);
  integer k;
  begin
   @(negedge clk);araddr=address;arvalid=1;
   do @(posedge clk);while(!arready);
   @(negedge clk);arvalid=0;
   while(!rvalid)begin @(posedge clk);#1;end
   check(rresp===expected_resp,"read response");
   if(expected_resp==0)check(rdata===expected_data,"read value and memory latency");
   for(k=0;k<hold_response;k=k+1)begin
    @(posedge clk);#1;check(rvalid && rresp===expected_resp,"R valid/resp stable under backpressure");
    if(expected_resp==0)check(rdata===expected_data,"R data stable under backpressure");
    check(!arready,"one outstanding read");
   end
   @(negedge clk);rready=1;@(posedge clk);@(negedge clk);rready=0;
  end
 endtask
 task automatic do_reset;
  begin
   @(negedge clk);resetn=0;awvalid=0;wvalid=0;arvalid=0;bready=0;rready=0;
   repeat(3)@(posedge clk);
   #1;check(!bvalid && !rvalid && !wr_en && !rd_en,"reset discards pending bus transactions");
   @(negedge clk);resetn=1;
  end
 endtask
 integer i,idx,baseline;reg [31:0] value;
 initial begin
  do_reset();
  // Full RAM write through capture port; then exclusively PS read/write traffic.
  for(i=0;i<TC_WORD_COUNT;i=i+1)begin
   @(negedge clk);capture_we=1;capture_address=i;capture_data=32'hC35A0000^i;
  end
  @(negedge clk);capture_we=0;
  for(i=0;i<200;i=i+1)begin
   value=32'h91E30000^(i*137);
   write_word(TC_CTRL_BASE+TC_REG_REQUEST_EPOCH,value,15,i%7,(i*3)%11,i%6,0);
   read_word(TC_CTRL_BASE+TC_REG_REQUEST_EPOCH,value,0,i%7);
   if(i%13==0)begin
    write_word(TC_CTRL_BASE+TC_REG_REQUEST_EPOCH,32'hBAD00000,3,1,0,3,2);
    read_word(TC_CTRL_BASE+TC_REG_REQUEST_EPOCH,value,0,2);
   end
  end
  // Concurrent independent read/write channels to different locations.
  fork
   write_word(TC_CTRL_BASE+TC_REG_REQUEST_EPOCH,32'h778899AA,15,12,1,7,0);
   read_word(TC_BRAM_BASE+4*12345,32'hC35A0000^12345,0,10);
  join
  for(i=0;i<40;i=i+1)begin
   idx=(i*1597)&65535;
   write_word(TC_BRAM_BASE+4*idx,32'hDEADBEEF,15,i%5,i%3,2,2);
   read_word(TC_BRAM_BASE+4*idx,32'hC35A0000^idx,0,4);
  end
  read_word(TC_BRAM_BASE,32'hC35A0000,0,0);
  read_word(TC_BRAM_BASE+TC_BRAM_RANGE-4,32'hC35AFFFF,0,8);
  read_word(TC_BRAM_BASE+1,0,2,4);
  read_word(TC_CTRL_BASE+1,0,2,4);
  // Reset after only AW, after only W, during B backpressure and R backpressure.
  baseline=accepted_writes;send_aw(TC_CTRL_BASE+TC_REG_REQUEST_EPOCH,0);do_reset();
  check(accepted_writes==baseline,"AW alone cannot write");
  send_w(32'h55667788,15,0);do_reset();check(accepted_writes==baseline,"W alone cannot write");
  fork send_aw(TC_CTRL_BASE+TC_REG_REQUEST_EPOCH,0);send_w(32'hAABBCCDD,15,0);join
  while(!bvalid)@(negedge clk);
  do_reset();check(accepted_writes==baseline+1,"reset with B stalled cannot duplicate committed write");
  @(negedge clk);arvalid=1;araddr=TC_BRAM_BASE;
  do @(posedge clk);while(!arready);
  @(negedge clk);arvalid=0;
  while(!rvalid)@(negedge clk);do_reset();
  read_word(TC_BRAM_BASE,32'hC35A0000,0,2);
  $display("PASS AXIL checks=%0d accepted_writes=%0d full_ram_words=%0d independent_AW_W_and_backpressure=covered PS_RAM_writes=rejected",checks,accepted_writes,TC_WORD_COUNT);
  $finish;
 end
 initial begin #20000000;$fatal(1,"TIMEOUT");end
endmodule
