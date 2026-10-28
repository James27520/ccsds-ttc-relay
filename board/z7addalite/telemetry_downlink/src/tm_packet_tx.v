// Finite, single-owner BPSK packet transmitter. Reset both mailbox domains together.
module tm_packet_tx #(parameter integer SYMBOL_CYCLES=2500)(
 input clk25,input reset25,input dac_clk,input dac_reset,input config_verified,
 input wr_en,input [31:0] wr_addr,input [31:0] wr_data,input [3:0] wr_strb,
 output reg wr_error,input [31:0] rd_addr,output reg [31:0] rd_data,output reg rd_error,
 output wire signed [15:0] dac_sample,output wire tx_active,
 output wire tx_bit,output reg tx_symbol_start
);
 localparam [31:0] DDS_STEP=32'd1554778161; // round(90.5 MHz / 250 MHz * 2^32)
 localparam [31:0] E_ADDR=1,E_PARTIAL=2,E_BUSY=4,E_LENGTH=8,
 E_OVERFLOW=16,E_NOTREADY=32,E_STOP=64,E_LOSS=128;
 (* ram_style="block" *) reg [31:0] packet_ram [0:127];
 reg [7:0] word_count=0;
 reg [31:0] bit_length=0,diag=0;
 reg owner=0,consumed=0,done_sticky=0,stop_request=0;
 wire cmd_ready,cmd_valid,done_ready,done_valid;
 wire [12:0] cmd_data;
 wire [1:0] done_data;
 reg cmd_send=0;
 reg [12:0] cmd_payload=0;
 reg done_pending=0;
 reg [1:0] done_reason=0;
 reg active=0;
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] cfg_sync=0,active_sync=0,stop_ack_sync=0;
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] stop_sync=0;
 wire ready=cfg_sync[2] && cmd_ready && !owner && !consumed && !stop_request && !stop_ack_sync[2];
 wire valid_wr_page=wr_addr[31:12]==20'h43c01 && wr_addr[1:0]==0;
 reg [31:0] write_fault;
 always @* begin
  write_fault=0;
  if(reset25)write_fault=E_NOTREADY;
  else if(!valid_wr_page)write_fault=E_ADDR;
  else if(wr_strb!=4'hf)write_fault=E_PARTIAL;
  else case(wr_addr[11:0])
   12'h008:if(wr_data!=1)write_fault=E_LENGTH;else if(owner || stop_ack_sync[2])write_fault=E_BUSY;
   12'h00c:if(owner)write_fault=E_BUSY;else if(word_count==128)write_fault=E_OVERFLOW;
   12'h010:if(owner)write_fault=E_BUSY;else if(wr_data==0 || wr_data>4096 || wr_data>{19'd0,word_count,5'd0})write_fault=E_LENGTH;
   12'h014:if(owner)write_fault=E_BUSY;else if(wr_data!=1 || bit_length==0 || bit_length>{19'd0,word_count,5'd0})write_fault=E_LENGTH;else if(!ready)write_fault=E_NOTREADY;
   12'h018:if(wr_data!=1)write_fault=E_LENGTH;
   default:write_fault=E_ADDR;
  endcase
  wr_error=write_fault!=0;
 end
 always @* begin
  rd_data=0;rd_error=0;
  if(rd_addr[31:12]!=20'h43c01 || rd_addr[1:0]!=0)rd_error=1;
  else case(rd_addr[11:0])
   12'h000:rd_data={24'd0,reset25,(stop_request || stop_ack_sync[2]),consumed,active_sync[2],done_sticky,(diag!=0),ready,owner};
   12'h004:rd_data=diag;
   12'h010,12'h024:rd_data=bit_length;
   12'h01c:rd_data=32'h544d5431;
   12'h020:rd_data=1;
   12'h028:rd_data={24'd0,word_count};
   default:rd_error=1;
  endcase
 end
 // A single sequential 32-bit write port; RAM contents do not need reset.
 always @(posedge clk25)begin
  if(wr_en && !reset25 && !wr_error && wr_addr[11:0]==12'h00c)
   packet_ram[word_count[6:0]]<=wr_data;
 end
 always @(posedge clk25)begin
  if(reset25)begin
   word_count<=0;bit_length<=0;diag<=0;owner<=0;consumed<=0;done_sticky<=0;
   stop_request<=0;cmd_send<=0;cmd_payload<=0;cfg_sync<=0;active_sync<=0;stop_ack_sync<=0;
  end else begin
   cfg_sync<={cfg_sync[1:0],config_verified};active_sync<={active_sync[1:0],active};
   stop_ack_sync<={stop_ack_sync[1:0],stop_sync[2]};cmd_send<=0;
   if(wr_en)begin
    if(wr_error)diag<=diag | write_fault;
    else case(wr_addr[11:0])
     12'h008:begin word_count<=0;bit_length<=0;diag<=0;consumed<=0;done_sticky<=0;end
     12'h00c:word_count<=word_count+1'b1;
     12'h010:bit_length<=wr_data;
     12'h014:begin owner<=1;consumed<=1;done_sticky<=0;cmd_payload<=bit_length[12:0];cmd_send<=1;end
     12'h018:if(owner)stop_request<=1;
    endcase
   end
   if(done_valid)begin
    owner<=0;stop_request<=0;done_sticky<=1;
    if(done_data==1)diag<=diag | E_STOP | ((wr_en && wr_error)?write_fault:0);
    if(done_data==2)diag<=diag | E_LOSS | ((wr_en && wr_error)?write_fault:0);
   end
  end
 end
 tc_mailbox #(.WIDTH(13)) tm_cmd_mailbox(
  .src_clk(clk25),.src_reset(reset25),.src_send(cmd_send),.src_data(cmd_payload),.src_ready(cmd_ready),
  .dst_clk(dac_clk),.dst_reset(dac_reset),.dst_valid(cmd_valid),.dst_data(cmd_data));
 tc_mailbox #(.WIDTH(2)) tm_done_mailbox(
  .src_clk(dac_clk),.src_reset(dac_reset),.src_send(done_pending),.src_data(done_reason),.src_ready(done_ready),
  .dst_clk(clk25),.dst_reset(reset25),.dst_valid(done_valid),.dst_data(done_data));
 reg [6:0] ram_addr=0;
 reg [31:0] ram_q;
 always @(posedge dac_clk)ram_q<=packet_ram[ram_addr];
 localparam integer SYMBOL_COUNTER_WIDTH=(SYMBOL_CYCLES<2)?1:$clog2(SYMBOL_CYCLES);
 reg [31:0] shift_word=0,phase=0;
 reg [SYMBOL_COUNTER_WIDTH-1:0] symbol_cycle=0;
 reg symbol_last=(SYMBOL_CYCLES==1);
 reg [12:0] remaining=0;
 reg [4:0] word_bit=0;
 reg [1:0] loading=0;
 reg signed [8:0] carrier=0;
 // A 64-entry 9-bit distributed sine ROM, fixed peak 128 / 32768.
 function signed [8:0] sine;
  input [5:0] a;
  begin case(a)
   0:sine=0;1:sine=13;2:sine=25;3:sine=37;4:sine=49;5:sine=60;6:sine=71;7:sine=81;
   8:sine=91;9:sine=99;10:sine=106;11:sine=113;12:sine=118;13:sine=122;14:sine=126;15:sine=127;
   16:sine=128;17:sine=127;18:sine=126;19:sine=122;20:sine=118;21:sine=113;22:sine=106;23:sine=99;
   24:sine=91;25:sine=81;26:sine=71;27:sine=60;28:sine=49;29:sine=37;30:sine=25;31:sine=13;
   32:sine=0;33:sine=-13;34:sine=-25;35:sine=-37;36:sine=-49;37:sine=-60;38:sine=-71;39:sine=-81;
   40:sine=-91;41:sine=-99;42:sine=-106;43:sine=-113;44:sine=-118;45:sine=-122;46:sine=-126;47:sine=-127;
   48:sine=-128;49:sine=-127;50:sine=-126;51:sine=-122;52:sine=-118;53:sine=-113;54:sine=-106;55:sine=-99;
   56:sine=-91;57:sine=-81;58:sine=-71;59:sine=-60;60:sine=-49;61:sine=-37;62:sine=-25;63:sine=-13;
  endcase end
 endfunction
 wire signed [8:0] bpsk_sample=tx_bit?carrier:-carrier;
 assign tx_active=active && config_verified && !dac_reset;
 assign tx_bit=shift_word[31];
 assign dac_sample=tx_active?{{7{bpsk_sample[8]}},bpsk_sample}:16'sd0;
 always @(posedge dac_clk)begin
  if(dac_reset)begin
   stop_sync<=0;active<=0;loading<=0;ram_addr<=0;shift_word<=0;
   phase<=0;carrier<=0;remaining<=0;word_bit<=0;symbol_cycle<=0;
   symbol_last<=(SYMBOL_CYCLES==1);
   tx_symbol_start<=0;done_pending<=0;done_reason<=0;
  end else begin
   stop_sync<={stop_sync[1:0],stop_request};tx_symbol_start<=0;
   if(done_pending && done_ready)done_pending<=0;
   if(cmd_valid)begin
    remaining<=cmd_data;ram_addr<=0;loading<=3;phase<=0;carrier<=0;
    word_bit<=0;symbol_cycle<=0;
    symbol_last<=(SYMBOL_CYCLES==1);
   end
   if(loading!=0)begin
    loading<=loading-1'b1;
    if(loading==1)begin
     shift_word<=ram_q;ram_addr<=1;active<=1;tx_symbol_start<=1;
    end
   end
   if(active)begin
    phase<=phase+DDS_STEP;carrier<=sine(phase[31:26]);
    if(symbol_last)begin
     symbol_cycle<=0;
     symbol_last<=(SYMBOL_CYCLES==1);
     // Shift even on the final boundary: output is gated by active. Keeping
     // length decoding out of the RAM-address CE shortens the 250 MHz path.
     if(word_bit==31)begin shift_word<=ram_q;ram_addr<=ram_addr+1'b1;word_bit<=0;end
     else begin shift_word<={shift_word[30:0],1'b0};word_bit<=word_bit+1'b1;end
     if(remaining==1)begin active<=0;done_pending<=1;done_reason<=0;end
     else begin
      remaining<=remaining-1'b1;tx_symbol_start<=1;
     end
    end else begin
     symbol_cycle<=symbol_cycle+1'b1;
     symbol_last<=(symbol_cycle==SYMBOL_CYCLES-2);
    end
   end
   // Cancellation covers both an in-flight command and an active packet.
   if((active || loading!=0 || cmd_valid) && (stop_sync[2] || !config_verified))begin
    active<=0;loading<=0;carrier<=0;tx_symbol_start<=0;
    done_pending<=1;done_reason<=!config_verified?2:1;
   end
  end
 end
endmodule
