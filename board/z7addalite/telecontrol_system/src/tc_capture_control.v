// Global clk25 domain. All ABI state and RAM write count live here.
module tc_capture_control #(parameter TIMEOUT_CYCLES=250000)(
 input clk,input reset,
 input wr_en,input [31:0] wr_addr,input [31:0] wr_data,input [3:0] wr_strb,output reg wr_error,
 input [31:0] rd_addr,output reg [31:0] rd_data,output reg rd_error,
 input config_busy,input config_verified,input [31:0] active_mode,input [31:0] config_epoch,input [111:0] live_diag,
 input training_valid,input training_parity,input [31:0] training_status,input stream_valid,input clock_alive,
 output reg mode_start,output reg mode_value,
 output command_send,input command_ready,output [37:0] command_data,
 input event_valid,input [37:0] event_data,input source_busy,
 input fifo_empty,input fifo_reset_busy,input [64:0] fifo_data,output fifo_read,
 output ram_write,output [15:0] ram_address,output [31:0] ram_data,
 output [3:0] phase_out
);
 `include "capture_abi.vh"
 reg [3:0] phase=TC_PHASE_IDLE;
 reg [31:0] result=0,error_code=0,request_epoch=0,request_select=0,request_mode=1;
 reg [31:0] snapshot_epoch=0,snapshot_select=0,snapshot_config_epoch=0,snapshot_flags=0;
 reg [111:0] snapshot_diag=0;
 reg [31:0] previous_epoch=0,mode_start_epoch=0;
 reg [16:0] words_written=0;
 reg command_pending=0;reg [37:0] pending_command=0;
 reg stop_ack=0,source_was_busy=0;reg [3:0] empty_stable=0;
 reg [31:0] timer=0;
 assign phase_out=phase;
 assign command_send=command_pending && command_ready;
 assign command_data=pending_command;
 wire capturing=phase==TC_PHASE_CAPTURING || phase==TC_PHASE_DRAINING;
 wire can_pop=!fifo_empty && !fifo_reset_busy && (capturing || phase==TC_PHASE_RELEASING);
 wire fifo_epoch_good=fifo_data[63:32]==snapshot_epoch;
 wire fifo_last_good=fifo_data[64]==(words_written==TC_WORD_COUNT-1);
 wire fifo_good=fifo_epoch_good && fifo_last_good && words_written<TC_WORD_COUNT;
 wire source_contract_good=config_verified && training_valid && stream_valid && clock_alive && !config_busy;
 assign fifo_read=can_pop;
 assign ram_write=can_pop && capturing && fifo_good && source_contract_good;
 assign ram_address=words_written[15:0];
 assign ram_data=fifo_data[31:0];
 wire [31:0] read_offset=rd_addr-TC_CTRL_BASE;
 wire [31:0] write_offset=wr_addr-TC_CTRL_BASE;
 wire ctrl_read_address=(rd_addr & ~(TC_CTRL_RANGE-1))==TC_CTRL_BASE && rd_addr[1:0]==0;
 wire ctrl_write_address=(wr_addr & ~(TC_CTRL_RANGE-1))==TC_CTRL_BASE && wr_addr[1:0]==0;
 always @*begin
  wr_error=!ctrl_write_address || wr_strb!=4'hF;
  case(write_offset)
   TC_REG_COMMAND:begin end
   TC_REG_REQUEST_EPOCH:if(phase!=TC_PHASE_IDLE)wr_error=1;
   TC_REG_REQUEST_SELECT:if(phase!=TC_PHASE_IDLE || wr_data>7)wr_error=1;
   TC_REG_REQUEST_MODE:if(phase!=TC_PHASE_IDLE || wr_data>1)wr_error=1;
   default:wr_error=1;
  endcase
 end
 always @*begin
  rd_error=!ctrl_read_address;rd_data=0;
  case(read_offset)
   TC_REG_MAGIC:rd_data=TC_MAGIC;
   TC_REG_ABI_VERSION:rd_data=TC_ABI_VERSION;
   TC_REG_STATUS:rd_data={22'd0,error_code!=0,config_busy,clock_alive,stream_valid,training_valid,config_verified,phase};
   TC_REG_LAST_COMMAND_RESULT:rd_data=result;
   TC_REG_CAPTURE_ERROR:rd_data=error_code;
   TC_REG_REQUEST_EPOCH:rd_data=request_epoch;
   TC_REG_REQUEST_SELECT:rd_data=request_select;
   TC_REG_SNAPSHOT_EPOCH:rd_data=snapshot_epoch;
   TC_REG_SNAPSHOT_SELECT:rd_data=snapshot_select;
   TC_REG_SAMPLE_COUNT:rd_data=TC_SAMPLE_COUNT;
   TC_REG_SAMPLES_WRITTEN:rd_data={14'd0,words_written,1'b0};
   TC_REG_SAMPLE_FORMAT:rd_data=TC_SAMPLE_FORMAT;
   TC_REG_ADC_RATE_HZ:rd_data=TC_ADC_RATE_HZ;
   TC_REG_OUTPUT_RATE_HZ:rd_data=TC_OUTPUT_RATE_HZ;
   TC_REG_CAPTURE_BYTES:rd_data=TC_CAPTURE_BYTES;
   TC_REG_REQUEST_MODE:rd_data=request_mode;
   TC_REG_ACTIVE_MODE:rd_data=active_mode;
   TC_REG_CONFIG_EPOCH:rd_data=config_epoch;
   TC_REG_SNAPSHOT_CONFIG_EPOCH:rd_data=snapshot_config_epoch;
   TC_REG_SNAPSHOT_FLAGS:rd_data=snapshot_flags;
   TC_REG_TRAINING_STATUS:rd_data=training_status;
   TC_REG_LIVE_DIAG0:rd_data=live_diag[31:0];
   TC_REG_LIVE_DIAG1:rd_data=live_diag[63:32];
   TC_REG_LIVE_DIAG2:rd_data=live_diag[95:64];
   TC_REG_LIVE_DIAG3:rd_data={16'd0,live_diag[111:96]};
   TC_REG_SNAPSHOT_DIAG0:rd_data=snapshot_diag[31:0];
   TC_REG_SNAPSHOT_DIAG1:rd_data=snapshot_diag[63:32];
   TC_REG_SNAPSHOT_DIAG2:rd_data=snapshot_diag[95:64];
   TC_REG_SNAPSHOT_DIAG3:rd_data={16'd0,snapshot_diag[111:96]};
   TC_REG_FRAMEWORK_BUILD_ID:rd_data=TC_FRAMEWORK_BUILD_ID;
   default:rd_error=1;
  endcase
 end
 task fail_capture(input [31:0] code);
  begin phase<=TC_PHASE_FAILED;error_code<=code;snapshot_flags[4]<=0;timer<=0;end
 endtask
 always @(posedge clk)begin
  if(reset)begin
   phase<=TC_PHASE_IDLE;result<=0;error_code<=0;request_epoch<=0;request_select<=0;request_mode<=1;
   snapshot_epoch<=0;snapshot_select<=0;snapshot_config_epoch<=0;snapshot_flags<=0;snapshot_diag<=0;
   previous_epoch<=0;words_written<=0;command_pending<=0;pending_command<=0;
   stop_ack<=0;source_was_busy<=0;empty_stable<=0;timer<=0;mode_start<=0;mode_value<=1;mode_start_epoch<=0;
  end else begin
   mode_start<=0;
   if(command_send)command_pending<=0;
   if(phase==TC_PHASE_ARMING || capturing || phase==TC_PHASE_RELEASING)begin
    if(timer<TIMEOUT_CYCLES)timer<=timer+1'b1;
   end else timer<=0;
   if(source_busy)source_was_busy<=1;
   if(capturing && source_was_busy && !source_busy)phase<=TC_PHASE_DRAINING;
   if(phase==TC_PHASE_CONFIGURING && config_epoch!=mode_start_epoch && !config_busy)phase<=TC_PHASE_IDLE;
   if(can_pop && capturing)begin
    if(!fifo_epoch_good)fail_capture(TC_ERROR_EPOCH_MISMATCH);
    else if(!fifo_last_good || words_written>=TC_WORD_COUNT)fail_capture(TC_ERROR_COUNT_LAST);
    else if(source_contract_good)begin
     words_written<=words_written+1'b1;
     if(words_written==TC_WORD_COUNT-1)begin phase<=TC_PHASE_DONE;snapshot_flags[4]<=1;timer<=0;end
    end
   end
   if(phase==TC_PHASE_RELEASING)begin
    if(stop_ack && fifo_empty && !fifo_reset_busy && !source_busy && !command_pending)begin
     if(empty_stable<8)empty_stable<=empty_stable+1'b1;
     if(empty_stable==7)begin phase<=TC_PHASE_IDLE;error_code<=0;words_written<=0;timer<=0;end
    end else empty_stable<=0;
   end
   if(event_valid && event_data[31:0]==snapshot_epoch)begin
    if(event_data[37:36]==1 && phase==TC_PHASE_ARMING)begin phase<=TC_PHASE_CAPTURING;timer<=0;end
    if(event_data[37:36]==2 && phase==TC_PHASE_RELEASING)stop_ack<=1;
    if(event_data[37:36]==3 && (phase==TC_PHASE_ARMING || capturing))fail_capture({28'd0,event_data[35:32]});
   end
   // These conditions take precedence over a coincident last RAM write.
   if(phase==TC_PHASE_ARMING || capturing)begin
    if(!clock_alive)fail_capture(TC_ERROR_CLOCK_TIMEOUT);
    else if(!config_verified || !training_valid || !stream_valid || config_busy)fail_capture(TC_ERROR_STREAM_INVALID);
    else if(timer>=TIMEOUT_CYCLES)fail_capture(phase==TC_PHASE_ARMING?TC_ERROR_ARM_TIMEOUT:TC_ERROR_CLOCK_TIMEOUT);
   end
   if(phase==TC_PHASE_RELEASING && timer>=TIMEOUT_CYCLES)fail_capture(TC_ERROR_CLOCK_TIMEOUT);
   if(wr_en && !wr_error)begin
    case(write_offset)
     TC_REG_REQUEST_EPOCH:request_epoch<=wr_data;
     TC_REG_REQUEST_SELECT:request_select<=wr_data;
     TC_REG_REQUEST_MODE:request_mode<=wr_data;
     TC_REG_COMMAND:begin
      result<=TC_RESULT_ACCEPTED;
      case(wr_data)
       TC_CMD_ARM:begin
        if(phase!=TC_PHASE_IDLE || config_busy || command_pending || !command_ready || !fifo_empty || fifo_reset_busy || source_busy)result<=TC_RESULT_BAD_STATE;
        else if(request_epoch==0 || request_epoch==previous_epoch || request_mode!=active_mode[0])result<=TC_RESULT_BAD_ARGUMENT;
        else if(!config_verified || !active_mode[31] || config_epoch==0)result<=TC_RESULT_NOT_VERIFIED;
        else if(!training_valid)result<=TC_RESULT_NOT_TRAINED;
        else if(!clock_alive || !stream_valid)result<=TC_RESULT_CLOCK_UNAVAILABLE;
        else begin
         snapshot_epoch<=request_epoch;previous_epoch<=request_epoch;
         snapshot_select<=request_select | (training_parity?TC_SNAPSHOT_PARITY_MASK:0);
         snapshot_config_epoch<=config_epoch;snapshot_diag<=live_diag;
         snapshot_flags<=TC_SNAPSHOT_TRAINING_VALID|TC_SNAPSHOT_CLOCK_ALIVE|(active_mode[0]?TC_SNAPSHOT_TRAINING_VERIFIED:TC_SNAPSHOT_NORMAL_VERIFIED);
         words_written<=0;error_code<=0;timer<=0;source_was_busy<=0;stop_ack<=0;empty_stable<=0;
         pending_command<={2'd1,training_parity,request_select[2:0],request_epoch};command_pending<=1;phase<=TC_PHASE_ARMING;
        end
       end
       TC_CMD_RELEASE:begin
        if(phase!=TC_PHASE_DONE && phase!=TC_PHASE_FAILED)result<=TC_RESULT_BAD_STATE;
        else begin
         phase<=TC_PHASE_RELEASING;stop_ack<=0;empty_stable<=0;timer<=0;
         pending_command<={2'd2,4'd0,snapshot_epoch};command_pending<=1;
        end
       end
       TC_CMD_APPLY_MODE:begin
        if(phase!=TC_PHASE_IDLE || config_busy || command_pending || source_busy)result<=TC_RESULT_BAD_STATE;
        else if(request_mode==TC_MODE_NORMAL && !training_valid)result<=TC_RESULT_NOT_TRAINED;
        else begin mode_start<=1;mode_value<=request_mode[0];mode_start_epoch<=config_epoch;phase<=TC_PHASE_CONFIGURING;end
       end
       TC_CMD_ABORT:begin
        if(phase!=TC_PHASE_ARMING && !capturing)result<=TC_RESULT_BAD_STATE;
        else fail_capture(TC_ERROR_ABORT);
       end
       default:result<=TC_RESULT_INVALID_COMMAND;
      endcase
     end
    endcase
   end
  end
 end
endmodule
