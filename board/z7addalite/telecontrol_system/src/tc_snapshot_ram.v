// 256 KiB capture RAM. PS write channel ALWAYS fails and cannot affect memory.
// Port A: capture writes; Port B: registered PS read. Both use global clk25.
module tc_snapshot_ram(
 input clk,input resetn,
 input capture_we,input [15:0] capture_word_address,input [31:0] capture_data,
 input rd_en,input [31:0] rd_addr,output reg [31:0] rd_data,output reg rd_error,
 output wr_error
);
 `include "capture_abi.vh"
 (* ram_style="block" *) reg [31:0] memory [0:TC_WORD_COUNT-1];
 assign wr_error=1'b1;
 // Never reset the memory array: only write the precise accepted capture words.
 always @(posedge clk)begin
  if(resetn && capture_we)memory[capture_word_address]<=capture_data;
  if(!resetn)begin rd_data<=0;rd_error<=0;end
  else if(rd_en)begin
   rd_error<=((rd_addr & ~(TC_BRAM_RANGE-1))!=TC_BRAM_BASE || rd_addr[1:0]!=0);
   if((rd_addr & ~(TC_BRAM_RANGE-1))==TC_BRAM_BASE && rd_addr[1:0]==0)rd_data<=memory[rd_addr[17:2]];
   else rd_data<=0;
  end
 end
endmodule
