// One outstanding AXI-Lite read and write, independently buffered AW/W.
// Backend reads have one synchronous memory cycle; backend writes commit on wr_en.
module tc_axil_frontend(
 input clk,input resetn,
 input [31:0] s_axi_awaddr,input [2:0] s_axi_awprot,input s_axi_awvalid,output s_axi_awready,
 input [31:0] s_axi_wdata,input [3:0] s_axi_wstrb,input s_axi_wvalid,output s_axi_wready,
 output reg [1:0] s_axi_bresp,output reg s_axi_bvalid,input s_axi_bready,
 input [31:0] s_axi_araddr,input [2:0] s_axi_arprot,input s_axi_arvalid,output s_axi_arready,
 output reg [31:0] s_axi_rdata,output reg [1:0] s_axi_rresp,output reg s_axi_rvalid,input s_axi_rready,
 output wr_en,output reg [31:0] wr_addr,output reg [31:0] wr_data,output reg [3:0] wr_strb,input wr_error,
 output rd_en,output reg [31:0] rd_addr,input [31:0] rd_data,input rd_error
);
 reg aw_pending,w_pending;
 reg [1:0] read_state;
 localparam R_IDLE=0,R_ISSUE=1,R_RETURN=2,R_RESPONSE=3;
 assign s_axi_awready=resetn && !aw_pending && !s_axi_bvalid;
 assign s_axi_wready=resetn && !w_pending && !s_axi_bvalid;
 assign wr_en=resetn && aw_pending && w_pending && !s_axi_bvalid;
 assign s_axi_arready=resetn && read_state==R_IDLE;
 assign rd_en=resetn && read_state==R_ISSUE;
 always @(posedge clk) begin
  if(!resetn) begin
   aw_pending<=0;w_pending<=0;wr_addr<=0;wr_data<=0;wr_strb<=0;
   s_axi_bresp<=0;s_axi_bvalid<=0;
   read_state<=R_IDLE;rd_addr<=0;s_axi_rdata<=0;s_axi_rresp<=0;s_axi_rvalid<=0;
  end else begin
   if(s_axi_awvalid && s_axi_awready)begin aw_pending<=1;wr_addr<=s_axi_awaddr;end
   if(s_axi_wvalid && s_axi_wready)begin w_pending<=1;wr_data<=s_axi_wdata;wr_strb<=s_axi_wstrb;end
   if(wr_en)begin
    aw_pending<=0;w_pending<=0;s_axi_bvalid<=1;s_axi_bresp<=wr_error?2'b10:2'b00;
   end else if(s_axi_bvalid && s_axi_bready)s_axi_bvalid<=0;
   case(read_state)
    R_IDLE:if(s_axi_arvalid && s_axi_arready)begin rd_addr<=s_axi_araddr;read_state<=R_ISSUE;end
    R_ISSUE:read_state<=R_RETURN;
    R_RETURN:begin s_axi_rdata<=rd_data;s_axi_rresp<=rd_error?2'b10:2'b00;s_axi_rvalid<=1;read_state<=R_RESPONSE;end
    R_RESPONSE:if(s_axi_rvalid && s_axi_rready)begin s_axi_rvalid<=0;read_state<=R_IDLE;end
   endcase
  end
 end
 // AXI PROT is transported by SmartConnect but does not select another ABI.
 wire unused_prot=^{s_axi_awprot,s_axi_arprot};
endmodule
