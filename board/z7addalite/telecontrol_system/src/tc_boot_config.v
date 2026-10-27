// Vendor LOOP clock table + actual AD9643 dual-channel DDR125 mode, guarded by reads.
module tc_boot_config #(
 parameter STARTUP_CYCLES=25000000, parameter PLL_WAIT_CYCLES=2500000,
 parameter SPI_HALF_CYCLES=50, parameter TIMEOUT_CYCLES=50000000
)(input clk,input reset,input adc_sdi,
 output clk_sclk,output clk_sda,output clk_cs,
 output adc_sclk,output adc_sda,output adc_sda_enable,output adc_cs,
 output reg config_done=0,output reg config_finished=0,
 output reg [111:0] diagnostic=0,output reg diagnostic_toggle=0,
 output [6:0] config_index);
 `include "tc_boot_words.vh"
 reg [6:0] index=0;
 reg [2:0] state=0;
 reg [24:0] wait_count=0;
 reg [25:0] watchdog=0;
 reg start=0;
 wire busy,done,sclk,sdo,sdo_enable,cs_n;wire [7:0] read_data;
 wire read_enable=(index==98 || index==100 || index==101 || index==102 || index==103 || index==104 || index==105 || index==107 || index==108 || index==109);
 assign config_index=index;
 wire target_adc=index>=76;
 assign clk_sclk=target_adc?1'b0:sclk;
 assign clk_sda=target_adc?1'b0:sdo;
 assign clk_cs=target_adc?1'b1:cs_n;
 assign adc_sclk=target_adc?sclk:1'b0;
 assign adc_sda=target_adc?sdo:1'b0;
 assign adc_sda_enable=target_adc && sdo_enable;
 assign adc_cs=target_adc?cs_n:1'b1;
 spi_rw24 #(.HALF_CYCLES(SPI_HALF_CYCLES)) transport(
 .clk(clk),.reset(reset),.start(start),.word(config_word(index)),.read_enable(read_enable),.sdi(adc_sdi),
 .busy(busy),.done(done),.sclk(sclk),.sdo(sdo),.sdo_enable(sdo_enable),.cs_n(cs_n),.read_data(read_data));
 reg [7:0] id_raw=0,a_format=0,b_format=0,a_ramp=0,b_ramp=0,divide_raw=0,phase_raw=0,delay_raw=0,a_index=0,b_index=0;
 reg [7:0] error_code=0,passed=0;
 reg [7:0] expected,mask,check_error;
 always @* begin
  expected=0;mask=8'hff;check_error=0;
  case(index)
   98:begin expected=8'h82;check_error=1;end
   100:begin expected=8'h01;mask=8'h03;check_error=2;end
   101:begin expected=8'h05;mask=8'h17;check_error=3;end
   102:begin expected=8'h06;mask=8'h8f;check_error=4;end
   103:begin expected=8'h00;mask=8'h3f;check_error=5;end
   104:begin expected=8'h00;mask=8'ha0;check_error=6;end
   105:begin expected=8'h00;mask=8'h9f;check_error=7;end
   107:begin expected=8'h02;mask=8'h03;check_error=8;end
   108:begin expected=8'h05;mask=8'h17;check_error=9;end
   109:begin expected=8'h04;mask=8'h8f;check_error=10;end
   default:begin expected=0;mask=0;check_error=0;end
  endcase
 end
 always @(posedge clk) begin
  start<=0;
  if(reset) begin
   index<=0;state<=0;wait_count<=0;watchdog<=0;config_done<=0;config_finished<=0;
   diagnostic<=0;diagnostic_toggle<=0;error_code<=0;passed<=0;
   id_raw<=0;a_format<=0;b_format<=0;a_ramp<=0;b_ramp<=0;divide_raw<=0;phase_raw<=0;delay_raw<=0;a_index<=0;b_index<=0;
  end else begin
   if(!config_finished && watchdog!=TIMEOUT_CYCLES)watchdog<=watchdog+1'b1;
   if(!config_finished && watchdog==TIMEOUT_CYCLES && state!=4)begin error_code<=11;state<=4;end
   else case(state)
    0:if(wait_count==STARTUP_CYCLES-1)begin wait_count<=0;state<=1;end else wait_count<=wait_count+1'b1;
    1:if(!busy)begin start<=1;state<=2;end
    2:if(done)begin
     case(index)
      98:id_raw<=read_data;
      100:a_index<=read_data;
      101:a_format<=read_data;
      102:a_ramp<=read_data;
      103:divide_raw<=read_data;
      104:phase_raw<=read_data;
      105:delay_raw<=read_data;
      107:b_index<=read_data;
      108:b_format<=read_data;
      109:b_ramp<=read_data;
     endcase
     if(read_enable && (read_data & mask)!==expected)begin error_code<=check_error;state<=4;end
     else begin
      if(read_enable)passed<=passed+1'b1;
      if(index==110)state<=4;
      else begin index<=index+1'b1;wait_count<=0;state<=3;end
     end
    end
    3:if(index==76 && wait_count!=PLL_WAIT_CYCLES-1)wait_count<=wait_count+1'b1;else state<=1;
    // One cycle after the final read, all raw NBA results are stable in this bundle.
    4:begin
     diagnostic<={8'h7d,(error_code==0 && passed==10)?8'ha1:8'he1,passed,error_code,b_index,a_index,delay_raw,phase_raw,divide_raw,b_ramp,a_ramp,b_format,a_format,id_raw};
     diagnostic_toggle<=~diagnostic_toggle;
     config_done<=(error_code==0 && passed==10);
     config_finished<=1;state<=5;
    end
    5:begin end
    default:begin error_code<=12;state<=4;end
   endcase
  end
 end
endmodule


