// Integration of the two real clock domains; large RAM stays on clk25.
module tc_capture_path #(parameter TIMEOUT_CYCLES=250000)(
 input clk25,input reset25,input fault_reset25,input clk_vec,input reset_vec,
 input [111:0] words,input stream_valid_vec,input training_valid_vec,input training_parity_vec,
 input training_failed_vec,input [15:0] training_count_vec,
 input config_busy,input config_verified,input [31:0] active_mode,input [31:0] config_epoch,input [111:0] live_diag,
 input wr_en,input [31:0] wr_addr,input [31:0] wr_data,input [3:0] wr_strb,output wr_error,
 input [31:0] rd_addr,output [31:0] rd_data,output rd_error,
 output mode_start,output mode_value,
 output ram_write,output [15:0] ram_address,output [31:0] ram_data,
 output clock_fault,output [3:0] capture_phase,output [31:0] training_status
);
 wire cmd_send,cmd_ready,cmd_valid;wire [37:0] cmd_data,cmd_received;
 wire event_send,event_ready,event_valid;wire [37:0] event_data,event_received;
 tc_mailbox #(.WIDTH(38)) command_mailbox(.src_clk(clk25),.src_reset(reset25),.src_send(cmd_send),.src_data(cmd_data),.src_ready(cmd_ready),
  .dst_clk(clk_vec),.dst_reset(reset_vec),.dst_valid(cmd_valid),.dst_data(cmd_received));
 tc_mailbox #(.WIDTH(38)) event_mailbox(.src_clk(clk_vec),.src_reset(reset_vec),.src_send(event_send),.src_data(event_data),.src_ready(event_ready),
  .dst_clk(clk25),.dst_reset(reset25),.dst_valid(event_valid),.dst_data(event_received));
 wire source_busy,fifo_full,wr_rst_busy,rd_rst_busy,fifo_write,fifo_read,fifo_empty;
 wire [64:0] fifo_input,fifo_output;
 tc_capture_source source(.clk(clk_vec),.reset(reset_vec),.stream_valid(stream_valid_vec),.training_valid(training_valid_vec),.words(words),
  .command_valid(cmd_valid),.command(cmd_received),.event_send(event_send),.event_ready(event_ready),.event_data(event_data),
  .fifo_full(fifo_full),.fifo_reset_busy(wr_rst_busy),.fifo_write(fifo_write),.fifo_data(fifo_input),.busy(source_busy));
 xpm_fifo_async #(.CDC_SYNC_STAGES(3),.DOUT_RESET_VALUE("0"),.ECC_MODE("no_ecc"),.FIFO_MEMORY_TYPE("block"),
  .FIFO_READ_LATENCY(0),.FIFO_WRITE_DEPTH(1024),.FULL_RESET_VALUE(0),.PROG_EMPTY_THRESH(16),.PROG_FULL_THRESH(16),
  .RD_DATA_COUNT_WIDTH(11),.READ_DATA_WIDTH(65),.READ_MODE("fwft"),.RELATED_CLOCKS(0),.SIM_ASSERT_CHK(1),
  .USE_ADV_FEATURES("0000"),.WAKEUP_TIME(0),.WRITE_DATA_WIDTH(65),.WR_DATA_COUNT_WIDTH(11)) crossing_fifo(
  .rst(reset_vec),.wr_clk(clk_vec),.rd_clk(clk25),.wr_en(fifo_write && !reset_vec),.din(fifo_input),.full(fifo_full),.wr_rst_busy(wr_rst_busy),
  .rd_en(fifo_read),.dout(fifo_output),.empty(fifo_empty),.rd_rst_busy(rd_rst_busy),.sleep(1'b0),.injectsbiterr(1'b0),.injectdbiterr(1'b0),
  .almost_empty(),.almost_full(),.data_valid(),.dbiterr(),.overflow(),.prog_empty(),.prog_full(),.rd_data_count(),.sbiterr(),.underflow(),.wr_ack(),.wr_data_count());
 // Training result snapshot is sent on semantic state changes, not each count.
 wire [31:0] training_desired={training_valid_vec?training_count_vec:16'd0,8'd1,5'd0,training_failed_vec,training_parity_vec,training_valid_vec};
 reg [31:0] training_sent=32'hFFFFFFFF;
 wire training_mail_ready,training_mail_valid;wire [31:0] training_received;
 wire training_mail_send=training_mail_ready && training_desired!=training_sent;
 always @(posedge clk_vec)if(reset_vec)training_sent<=32'hFFFFFFFF;else if(training_mail_send)training_sent<=training_desired;
 tc_mailbox #(.WIDTH(32)) training_mailbox(.src_clk(clk_vec),.src_reset(reset_vec),.src_send(training_mail_send),.src_data(training_desired),.src_ready(training_mail_ready),
  .dst_clk(clk25),.dst_reset(reset25),.dst_valid(training_mail_valid),.dst_data(training_received));
 reg [31:0] training_snapshot=0;
 always @(posedge clk25)if(reset25)training_snapshot<=0;else if(training_mail_valid)training_snapshot<=training_received;
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] busy_sync=0,stream_sync=0,valid_sync=0,heartbeat_sync=0;
 // stream_valid_vec is a same-domain combinational readiness predicate. Launch
 // a register into the asynchronous status synchronizer so combinational
 // decode glitches cannot become a false ready/failure in the clk25 domain.
 // The source capture engine still consumes stream_valid_vec immediately.
 reg stream_valid_registered=0;
 always @(posedge clk_vec)if(reset_vec)stream_valid_registered<=0;else stream_valid_registered<=stream_valid_vec;
 reg [9:0] heartbeat_counter=0;
 // Observe the physical clock even while PS/capture reset is held. Resetting
 // this counter with reset_vec would falsely report a stopped DCO after a long
 // PS restart. Configuration initializes it; only transitions, not its phase,
 // matter to the independently globally-reset watchdog below.
 always @(posedge clk_vec)heartbeat_counter<=heartbeat_counter+1'b1;
 reg heartbeat_seen=0,clock_alive=0,clock_fault_reg=0,had_clock=0;
 reg [31:0] heartbeat_timeout=0;
 always @(posedge clk25)begin
  if(reset25)begin busy_sync<=0;stream_sync<=0;valid_sync<=0;end
  else begin
   busy_sync<={busy_sync[1:0],source_busy};stream_sync<={stream_sync[1:0],stream_valid_registered};
   valid_sync<={valid_sync[1:0],training_valid_vec};
  end
 end
 // A PS restart does not reset the BUFR/ISERDES and therefore must not clear
 // a latched DCO-stop condition. Only the full design initialization can do so.
 always @(posedge clk25)begin
  if(fault_reset25)begin
   heartbeat_sync<=0;heartbeat_seen<=0;heartbeat_timeout<=0;
   clock_alive<=0;clock_fault_reg<=0;had_clock<=0;
  end else begin
   heartbeat_sync<={heartbeat_sync[1:0],heartbeat_counter[9]};
   if(heartbeat_sync[2]!=heartbeat_seen)begin
    heartbeat_seen<=heartbeat_sync[2];heartbeat_timeout<=0;clock_alive<=1;had_clock<=1;
   end else if(heartbeat_timeout<TIMEOUT_CYCLES)heartbeat_timeout<=heartbeat_timeout+1'b1;
   else begin clock_alive<=0;if(had_clock)clock_fault_reg<=1;end
  end
 end
 assign clock_fault=clock_fault_reg;
 wire training_good=training_snapshot[0] && valid_sync[2] && !clock_fault_reg;
 assign training_status={training_snapshot[31:3],training_snapshot[2]|clock_fault_reg,training_snapshot[1],training_good};
 tc_capture_control #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) control(.clk(clk25),.reset(reset25),
  .wr_en(wr_en),.wr_addr(wr_addr),.wr_data(wr_data),.wr_strb(wr_strb),.wr_error(wr_error),
  .rd_addr(rd_addr),.rd_data(rd_data),.rd_error(rd_error),
  .config_busy(config_busy),.config_verified(config_verified),.active_mode(active_mode),.config_epoch(config_epoch),.live_diag(live_diag),
  .training_valid(training_good),.training_parity(training_snapshot[1]),.training_status(training_status),.stream_valid(stream_sync[2]),.clock_alive(clock_alive),
  .mode_start(mode_start),.mode_value(mode_value),.command_send(cmd_send),.command_ready(cmd_ready),.command_data(cmd_data),
  .event_valid(event_valid),.event_data(event_received),.source_busy(busy_sync[2]),
  .fifo_empty(fifo_empty),.fifo_reset_busy(rd_rst_busy),.fifo_data(fifo_output),.fifo_read(fifo_read),
  .ram_write(ram_write),.ram_address(ram_address),.ram_data(ram_data),.phase_out(capture_phase));
endmodule
