`timescale 1ns/1ps
module tb_capture;
 `include "capture_abi.vh"
 reg clk25=0;always #20 clk25=~clk25;
 reg clk_vec=0,run_source=1;always begin #16;if(run_source)clk_vec=~clk_vec;else clk_vec=0;end
 reg reset25=1,reset_vec=1,fault_reset25=1;
 reg [111:0] words=0;integer vector_number=0;
 reg stream_valid=1,train_valid=1,parity=0,train_failed=0;
 reg config_busy=0,config_verified=1;reg [31:0] active_mode=32'h80000001,config_epoch=1;
 reg [111:0] diag=112'h7DA10A0002010000000406050582;
 reg wr_en=0;reg [31:0] wr_addr=0,wr_data=0,rd_addr=0;reg [3:0] wr_strb=15;
 wire wr_error,rd_error;wire [31:0] rd_data;
 wire mode_start,mode_value,ram_write,clock_fault;wire [15:0] ram_address;wire [31:0] ram_data,training_status;
 wire [3:0] phase;
 tc_capture_path dut(.clk25(clk25),.reset25(reset25),.fault_reset25(fault_reset25),.clk_vec(clk_vec),.reset_vec(reset_vec),
 .words(words),.stream_valid_vec(stream_valid),.training_valid_vec(train_valid),.training_parity_vec(parity),.training_failed_vec(train_failed),.training_count_vec(16'd128),
 .config_busy(config_busy),.config_verified(config_verified),.active_mode(active_mode),.config_epoch(config_epoch),.live_diag(diag),
 .wr_en(wr_en),.wr_addr(wr_addr),.wr_data(wr_data),.wr_strb(wr_strb),.wr_error(wr_error),.rd_addr(rd_addr),.rd_data(rd_data),.rd_error(rd_error),
 .mode_start(mode_start),.mode_value(mode_value),.ram_write(ram_write),.ram_address(ram_address),.ram_data(ram_data),
 .clock_fault(clock_fault),.capture_phase(phase),.training_status(training_status));
 integer checks=0,k,word_index,expected_address=0,ram_writes=0,full_captures=0;
 integer requested_channel=0,requested_k=0;
 reg [31:0] expected_queue[$];reg [15:0] first_golden;reg half_golden=0;
 reg [13:0] chosen;reg [15:0] signed_chosen;reg [31:0] popped;
 reg [31:0] memory [0:65535];
 task automatic check(input bit okay,input string message);
  begin checks=checks+1;if(!okay)$fatal(1,"CHECK_FAIL %s phase%0d at %t",message,phase,$time);end
 endtask
 always @(negedge clk_vec)begin
  if(reset_vec)vector_number=0;else vector_number=vector_number+1;
  for(integer j=0;j<4;j=j+1)begin
   words[(2*j+parity)*14 +:14]=(vector_number*4+j)&14'h3FFF;
   words[(2*j+1-parity)*14 +:14]=(j&1)?14'h1555:14'h2AAA;
  end
 end
 // Independent contract scoreboard observes source sample epochs, not FIFO data.
 always @(posedge clk_vec)begin
  if(!reset_vec && dut.source.busy && !dut.cmd_valid && stream_valid && train_valid && !dut.wr_rst_busy)begin
   chosen=words[(2*requested_k+(parity^requested_channel))*14 +:14];
   signed_chosen={{2{chosen[13]}},chosen};
   if(!half_golden)begin first_golden=signed_chosen;half_golden=1;end
   else begin expected_queue.push_back({signed_chosen,first_golden});half_golden=0;end
  end
 end
 always @(posedge clk25)if(!reset25 && ram_write)begin
  check(expected_queue.size()>0,"RAM write must have chronological source samples");
  popped=expected_queue.pop_front();
  check(ram_data===popped,"sample selection/sign extension/packing/CDC");
  check(ram_address==expected_address,"RAM address counts actual commits");
  memory[ram_address]=ram_data;expected_address=expected_address+1;ram_writes=ram_writes+1;
 end
 task automatic write_reg(input [31:0] offset,input [31:0] value);
  begin
   @(negedge clk25);wr_addr=TC_CTRL_BASE+offset;wr_data=value;wr_en=1;wr_strb=15;
   #1;check(!wr_error,"legal register write");
   @(posedge clk25);@(negedge clk25);wr_en=0;
  end
 endtask
 task automatic expect_reg(input [31:0] offset,input [31:0] value);
  begin rd_addr=TC_CTRL_BASE+offset;#1;check(!rd_error && rd_data===value,"register value");end
 endtask
 task automatic wait_phase(input integer target);
  integer n;
  begin
   n=0;while(phase!=target && n<600000)begin @(posedge clk25);#1;n=n+1;end
   check(phase==target,"phase reached before watchdog test deadline");
  end
 endtask
 task automatic fresh;
  begin
   @(negedge clk25);reset25=1;reset_vec=1;fault_reset25=1;wr_en=0;run_source=1;
   stream_valid=1;train_valid=1;train_failed=0;config_busy=0;config_verified=1;active_mode=32'h80000001;config_epoch=1;
   repeat(40)@(posedge clk25);
   @(negedge clk25);reset25=0;fault_reset25=0;
   @(negedge clk_vec);reset_vec=0;
   repeat(1300)@(posedge clk25);
   expected_queue.delete();half_golden=0;expected_address=0;ram_writes=0;
   check(training_status[0] && dut.clock_alive,"training mailbox and live source heartbeat");
  end
 endtask
 task automatic arm(input [31:0] epoch,input integer channel,input integer sample_k);
  begin
   requested_channel=channel;requested_k=sample_k;
   expected_queue.delete();half_golden=0;expected_address=0;ram_writes=0;
   write_reg(TC_REG_REQUEST_EPOCH,epoch);write_reg(TC_REG_REQUEST_SELECT,(sample_k<<1)|channel);
   write_reg(TC_REG_COMMAND,TC_CMD_ARM);expect_reg(TC_REG_LAST_COMMAND_RESULT,TC_RESULT_ACCEPTED);
   wait_phase(TC_PHASE_CAPTURING);
  end
 endtask
 task automatic release_snapshot;
  begin
   write_reg(TC_REG_COMMAND,TC_CMD_RELEASE);wait_phase(TC_PHASE_IDLE);
   check(!dut.source.busy && dut.fifo_empty,"release waits for source stop and FIFO drain");
   expected_queue.delete();half_golden=0;
  end
 endtask
 reg [31:0] frozen_word;integer n;
 initial begin
  fresh();expect_reg(TC_REG_MAGIC,TC_MAGIC);expect_reg(TC_REG_ABI_VERSION,TC_ABI_VERSION);
  for(n=0;n<4;n=n+1)begin
   parity=n[0];fresh();arm(n+1,n>=2,n%4);
   repeat(20)@(posedge clk25);
   write_reg(TC_REG_COMMAND,TC_CMD_ARM);expect_reg(TC_REG_LAST_COMMAND_RESULT,TC_RESULT_BAD_STATE);
   if(n==0)begin
    while(dut.control.words_written<65528)@(negedge clk25);
    force dut.fifo_empty=1'b1;
    while(dut.source.busy)@(negedge clk25);
    repeat(20)@(posedge clk25);
    check(phase!=TC_PHASE_DONE && dut.control.words_written<65536,"source completion cannot publish DONE before RAM commits");
    release dut.fifo_empty;
   end
   wait_phase(TC_PHASE_DONE);
   check(ram_writes==65536 && expected_queue.size()==0,"complete 131072 sample snapshot without drops");
   expect_reg(TC_REG_SAMPLES_WRITTEN,131072);expect_reg(TC_REG_SNAPSHOT_EPOCH,n+1);
   expect_reg(TC_REG_SNAPSHOT_FLAGS,TC_SNAPSHOT_TRAINING_VERIFIED|TC_SNAPSHOT_TRAINING_VALID|TC_SNAPSHOT_CLOCK_ALIVE|TC_SNAPSHOT_CAPTURE_SUCCESS);
   frozen_word=memory[12345];repeat(100)@(posedge clk25);
   check(!ram_write && memory[12345]===frozen_word,"DONE snapshot frozen");
   write_reg(TC_REG_COMMAND,TC_CMD_ARM);expect_reg(TC_REG_LAST_COMMAND_RESULT,TC_RESULT_BAD_STATE);
   release_snapshot();
   write_reg(TC_REG_COMMAND,TC_CMD_ARM);expect_reg(TC_REG_LAST_COMMAND_RESULT,TC_RESULT_BAD_ARGUMENT);
   full_captures=full_captures+1;
  end
  // Failure path: explicit abort and immediate re-arm only after release.
  arm(100,0,0);repeat(30)@(posedge clk25);write_reg(TC_REG_COMMAND,TC_CMD_ABORT);
  wait_phase(TC_PHASE_FAILED);expect_reg(TC_REG_CAPTURE_ERROR,TC_ERROR_ABORT);release_snapshot();
  arm(101,0,1);force dut.fifo_full=1'b1;
  wait_phase(TC_PHASE_FAILED);release dut.fifo_full;expect_reg(TC_REG_CAPTURE_ERROR,TC_ERROR_FIFO_OVERFLOW);release_snapshot();
  arm(102,0,2);@(negedge clk25);config_verified=0;
  wait_phase(TC_PHASE_FAILED);expect_reg(TC_REG_CAPTURE_ERROR,TC_ERROR_STREAM_INVALID);config_verified=1;release_snapshot();
  arm(103,0,0);
  while(dut.fifo_empty)@(negedge clk25);
  force dut.fifo_output={1'b0,32'hDEADBEEF,32'h01020304};
  wait_phase(TC_PHASE_FAILED);release dut.fifo_output;expect_reg(TC_REG_CAPTURE_ERROR,TC_ERROR_EPOCH_MISMATCH);release_snapshot();
  arm(104,0,0);@(negedge clk_vec);run_source=0;
  wait_phase(TC_PHASE_FAILED);expect_reg(TC_REG_CAPTURE_ERROR,TC_ERROR_CLOCK_TIMEOUT);
  check(clock_fault,"independent clk25 watchdog latches loss while source stopped");
  @(negedge clk25);reset25=1;reset_vec=1;
  repeat(20)@(posedge clk25);check(clock_fault,"PS-only reset cannot clear DCO fault");
  run_source=1;repeat(40)@(posedge clk25);
  @(negedge clk25);reset25=0;reset_vec=0;
  repeat(1300)@(posedge clk25);check(clock_fault && !training_status[0],"clock return and PS restart do not bypass full reinit");
  fresh();
  // A prolonged PS reset must not stop the independent DCO heartbeat.
  // Keep the source clock running beyond the 10ms watchdog interval.
  @(negedge clk25);reset25=1;reset_vec=1;
  repeat(250100)@(posedge clk25);
  check(!clock_fault,"long PS-only reset with running DCO cannot create a clock fault");
  @(negedge clk25);reset25=0;reset_vec=0;
  repeat(1300)@(posedge clk25);
  check(!clock_fault && training_status[0] && dut.clock_alive,"healthy DCO survives long PS restart");
  $display("PASS CAPTURE checks=%0d full_captures=%0d samples=%0d XPM_FIFO=actual overflow/epoch/clockstop/abort/late_last/rearm=covered",checks,full_captures,full_captures*131072);
  $finish;
 end
 initial begin #100000000;$fatal(1,"TIMEOUT capture test");end
endmodule
