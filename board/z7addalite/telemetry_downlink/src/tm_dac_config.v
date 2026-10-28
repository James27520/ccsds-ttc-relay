// One-shot AD9122 configuration for word mode / signed I,Q / 4x interpolation.
// Write values originate in adda_probe/vendor/ad9122_config.v and the reviewed
// spi_read_review/ad9122_config_guarded.v. New read gates follow AD9122 Rev.C.
// clk25 only; hardware RESET# and running 250MHz DCI are owned by the top.
module tm_dac_config #(
 parameter SPI_HALF_CYCLES=50,
 parameter CONFIG_TIMEOUT_CYCLES=25000000
)(input clk25,input reset,input start_allowed,input sdi,
 output sdo,output sdo_enable,output cs_n,output sclk,
 output reg verified=0,output reg finished=0,
 output reg [31:0] diagnostic=0);
 localparam WAIT_START=0,ISSUE=1,WAIT_SPI=2,CHECK=3,STOP=4;
 reg [2:0] state=WAIT_START;
 reg [5:0] step=0;
 reg [31:0] elapsed=0;
 reg spi_start=0;
 wire busy,done,fault;
 wire [7:0] rd;
 wire is_read=(step==25 || step==27 || step>=28);
 function [15:0] operation;
  input [5:0] n;
  begin case(n)
   0:operation=16'h00a0; 1:operation=16'h0080;
   2:operation=16'h0300; 3:operation=16'h0400;
   4:operation=16'h0500; 5:operation=16'h08a0;
   6:operation=16'h0a00; 7:operation=16'h0c00;
   8:operation=16'h0d00; 9:operation=16'h1000;
   10:operation=16'h1100;11:operation=16'h1603;
   12:operation=16'h1ba4;13:operation=16'h1c00;
   14:operation=16'h1d00;15:operation=16'h1e01;
   16:operation=16'h3000;17:operation=16'h3100;
   18:operation=16'h3200;19:operation=16'h3300;
   20:operation=16'h3601;21:operation=16'h3600;
   22:operation=16'h1048;23:operation=16'h1704;
   24:operation=16'h1802;25:operation=16'h9800;
   26:operation=16'h1800;27:operation=16'h9800;
   28:operation=16'h9900;29:operation=16'hff00;
   30:operation=16'h8000;31:operation=16'h8300;
   32:operation=16'h8800;33:operation=16'h8a00;
   34:operation=16'h9000;35:operation=16'h9100;
   36:operation=16'h9600;37:operation=16'h9b00;
   38:operation=16'h9c00;39:operation=16'h9d00;
   40:operation=16'h9e00;41:operation=16'h9700;42:operation=16'h8100;
   default:operation=0;
  endcase end
 endfunction
 reg [7:0] mask,expected;
 always @* begin
  mask=8'hff;expected=0;
  case(step)
   25:begin mask=8'hc6;expected=8'h06;end
   27:begin mask=8'hc6;expected=0;end
   29:begin mask=8'h3c;expected=8'h0c;end // R2 only; R1 lacks DCI delay.
   30:begin mask=8'he0;expected=8'h80;end // bidirectional, MSB-first, reset off
   31:begin mask=8'he3;expected=0;end // two's complement, I first, word
   32:begin mask=8'hff;expected=8'ha0;end // DACCLK input enabled
   33:begin mask=8'h80;expected=0;end // internal PLL disabled
   34:begin mask=8'hc8;expected=8'h48;end // sync disabled/data-rate selected
   35:begin mask=8'hff;expected=0;end
   36:begin mask=8'h03;expected=3;end
   37:begin mask=8'hff;expected=8'ha4;end // premod/NCO bypass, no I->Q
   38:begin mask=8'h07;expected=0;end // HB1 2x lowpass
   39:begin mask=8'h7f;expected=0;end // HB2 2x lowpass
   40:begin mask=8'h7f;expected=1;end // HB3 bypass
   41:begin mask=8'h07;expected=4;end
   42:begin mask=8'he0;expected=0;end // I/Q DACs and LVDS receiver powered
   default:begin mask=8'hff;expected=0;end
  endcase
 end
 wire [15:0] spi_word=operation(step);
 tm_spi16 #(.HALF_CYCLES(SPI_HALF_CYCLES)) spi(
  .clk(clk25),.reset(reset || finished),.start(spi_start),
  .word(spi_word),.read_enable(is_read),.sdi(sdi),
  .busy(busy),.done(done),.fault(fault),.read_data(rd),
  .sdo(sdo),.sdo_enable(sdo_enable),.cs_n(cs_n),.sclk(sclk));
 // diagnostic: [31:28] result (0 idle,1 pass,2 read mismatch,3 deadline,
 // 4 prerequisite lost,5 pin echo fault); [27:24] reserved; [23:16] step;
 // [15:8] register address; [7:0] actual final read byte.
 task fail;
  input [3:0] reason;
  begin verified<=0;finished<=1;state<=STOP;
   diagnostic<={reason,4'd0,2'd0,step,1'b0,spi_word[14:8],rd};
  end
 endtask
 always @(posedge clk25) begin
  spi_start<=0;
  if(reset) begin
   state<=WAIT_START;step<=0;elapsed<=0;verified<=0;finished<=0;diagnostic<=0;
  end else if(state!=WAIT_START && state!=STOP && !start_allowed) fail(4);
  else if(state!=WAIT_START && state!=STOP && elapsed>=CONFIG_TIMEOUT_CYCLES-1) fail(3);
  else begin
   if(state!=WAIT_START && state!=STOP) elapsed<=elapsed+1'b1;
   case(state)
    WAIT_START:if(start_allowed) state<=ISSUE;
    ISSUE:if(!busy) begin spi_start<=1;state<=WAIT_SPI;end
    WAIT_SPI:if(done) begin if(fault) fail(5);else state<=CHECK;end
    CHECK:begin
     if(!is_read) begin step<=step+1'b1;state<=ISSUE;end
     else if(step==28) begin
      if(rd===8'h07 || rd===8'h0f || rd===8'h1f) begin step<=29;state<=ISSUE;end
      else state<=ISSUE; // bounded polling, no reconfiguration retry
     end else if((rd & mask) === expected) begin
      if(step==42) begin
       verified<=1;finished<=1;state<=STOP;
       diagnostic<={4'd1,4'd0,8'd42,8'h01,rd};
      end else begin step<=step+1'b1;state<=ISSUE;end
     end else if(step==25 || step==27) state<=ISSUE;
     else fail(2);
    end
    STOP:begin
     // A lost clock prerequisite invalidates success until explicit reset.
     if(verified && !start_allowed) fail(4);
    end
    default:fail(2);
   endcase
  end
 end
endmodule
