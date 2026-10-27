// Single-entry bundled-data CDC with acknowledgement. Sender keeps payload
// stable from accepted send until returned ack; no free-running multi-bit bus.
module tc_mailbox #(parameter WIDTH=32)(
 input src_clk,input src_reset,input src_send,input [WIDTH-1:0] src_data,output src_ready,
 input dst_clk,input dst_reset,output reg dst_valid,output reg [WIDTH-1:0] dst_data
);
 reg [WIDTH-1:0] held_data=0;reg send_toggle=0;
 reg ack_toggle=0;
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] ack_sync=0,toggle_sync=0;
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [WIDTH-1:0] data_meta=0,data_sync=0;
 assign src_ready=!src_reset && ack_sync[2]==send_toggle;
 always @(posedge src_clk)begin
  if(src_reset)begin held_data<=0;send_toggle<=0;ack_sync<=0;end
  else begin
   ack_sync<={ack_sync[1:0],ack_toggle};
   if(src_send && src_ready)begin held_data<=src_data;send_toggle<=~send_toggle;end
  end
 end
 always @(posedge dst_clk)begin
  if(dst_reset)begin data_meta<=0;data_sync<=0;toggle_sync<=0;ack_toggle<=0;dst_data<=0;dst_valid<=0;end
  else begin
   data_meta<=held_data;data_sync<=data_meta;toggle_sync<={toggle_sync[1:0],send_toggle};
   dst_valid<=0;
   if(toggle_sync[2]!=ack_toggle)begin
    dst_data<=data_sync;dst_valid<=1;ack_toggle<=toggle_sync[2];
   end
  end
 end
endmodule
