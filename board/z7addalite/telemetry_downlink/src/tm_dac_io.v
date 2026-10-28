// AD9122 word-mode DDR: I on rising DCI, Q=0 on falling DCI.
// DCI is edge aligned; the DAC's read-verified delay setting is 3.
module tm_dac_io(input dac_clk,input reset,input signed [15:0] sample,
 output dci_p,output dci_n,output frame_p,output frame_n,
 output [15:0] data_p,output [15:0] data_n);
 // Separate modulation arithmetic from the bank's ODDR setup path. This adds
 // one constant DAC clock of latency to the entire finite burst.
 (* KEEP="TRUE" *) reg signed [15:0] staged_sample=0;
 always @(posedge dac_clk or posedge reset)
  if(reset)staged_sample<=0;else staged_sample<=sample;
 wire forwarded;
 ODDR #(.DDR_CLK_EDGE("SAME_EDGE"),.INIT(1'b0),.SRTYPE("ASYNC"))
 dci_reg(.C(dac_clk),.CE(1'b1),.D1(1'b1),.D2(1'b0),.R(reset),.S(1'b0),.Q(forwarded));
 OBUFDS #(.IOSTANDARD("LVDS_25")) dci_buf(.I(forwarded),.O(dci_p),.OB(dci_n));
 OBUFDS #(.IOSTANDARD("LVDS_25")) frame_buf(.I(1'b0),.O(frame_p),.OB(frame_n));
 genvar lane;
 generate for(lane=0;lane<16;lane=lane+1)begin:lanes
  wire serial_data;
  ODDR #(.DDR_CLK_EDGE("SAME_EDGE"),.INIT(1'b0),.SRTYPE("ASYNC"))
  data_reg(.C(dac_clk),.CE(1'b1),.D1(staged_sample[lane]),.D2(1'b0),.R(reset),.S(1'b0),.Q(serial_data));
  OBUFDS #(.IOSTANDARD("LVDS_25")) data_buf(.I(serial_data),.O(data_p[lane]),.OB(data_n[lane]));
 end endgenerate
endmodule
