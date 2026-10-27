// Regional CLKDIV domain only: select one of 4 samples/channel, sign extend,
// pair chronological int16 samples and write tagged records to async FIFO.
module tc_capture_source(
 input clk,input reset,input stream_valid,input training_valid,input [111:0] words,
 input command_valid,input [37:0] command,
 output event_send,input event_ready,output [37:0] event_data,
 input fifo_full,input fifo_reset_busy,output reg fifo_write,output reg [64:0] fifo_data,
 output reg busy
);
 `include "capture_abi.vh"
 reg [31:0] active_epoch;
 reg [2:0] word_index;
 reg [17:0] samples;
 reg half_full;reg [15:0] first_sample;
 reg event_pending;reg [37:0] pending_event;
 wire [13:0] raw=words[word_index*14 +: 14];
 wire [15:0] sample={{2{raw[13]}},raw};
 assign event_send=event_pending && event_ready;
 assign event_data=pending_event;
 // Event type: 1 arm accepted, 2 stop acknowledged, 3 error; error nibble
 // matches TC_ERROR values, epoch is always the command/capture epoch.
 task queue_error(input [3:0] error_code);
  begin busy<=0;half_full<=0;event_pending<=1;pending_event<={2'd3,error_code,active_epoch};end
 endtask
 always @(posedge clk)begin
  if(reset)begin
   active_epoch<=0;word_index<=0;samples<=0;half_full<=0;first_sample<=0;
   event_pending<=0;pending_event<=0;fifo_write<=0;fifo_data<=0;busy<=0;
  end else begin
   fifo_write<=0;
   if(event_send)event_pending<=0;
   if(command_valid)begin
    if(command[37:36]==2)begin
     busy<=0;half_full<=0;samples<=0;
     event_pending<=1;pending_event<={2'd2,4'd0,command[31:0]};
    end else if(command[37:36]==1)begin
     active_epoch<=command[31:0];samples<=0;half_full<=0;
     word_index<={command[34:33],command[35]^command[32]};
     event_pending<=1;
     if(!busy && stream_valid && training_valid && !fifo_reset_busy)begin
      busy<=1;pending_event<={2'd1,4'd0,command[31:0]};
     end else begin busy<=0;pending_event<={2'd3,4'd4,command[31:0]};end
    end
   end else if(busy)begin
    if(!stream_valid || !training_valid || fifo_reset_busy)queue_error(4'd4);
    else begin
     samples<=samples+1'b1;
     if(!half_full)begin first_sample<=sample;half_full<=1;end
     else if(fifo_full)queue_error(4'd2);
     else begin
      fifo_write<=1;fifo_data<={samples==TC_SAMPLE_COUNT-1,active_epoch,sample,first_sample};
      half_full<=0;
      if(samples==TC_SAMPLE_COUNT-1)busy<=0;
     end
    end
   end
  end
 end
endmodule
