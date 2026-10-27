// Boot clocks once; runtime changes only AD9643 test selection and reads it back.
// All ports and diagnostic publication are synchronous to clk25.
module tc_adc_config #(
 parameter STARTUP_CYCLES=25000000, parameter PLL_WAIT_CYCLES=2500000,
 parameter SPI_HALF_CYCLES=50, parameter TIMEOUT_CYCLES=50000000
)(input clk25,input reset,input mode_start,input mode_value,input adc_sdi,
 output clk_sclk,output clk_sda,output clk_cs,
 output adc_sclk,output adc_sdo,output adc_sdo_enable,output adc_cs,
 output reg startup_finished=0,output reg config_busy=1,output reg config_verified=0,
 output reg [31:0] active_mode=0,output reg [31:0] config_epoch=0,
 output reg [111:0] diagnostic=0,output reg result_toggle=0);
 wire boot_sclk,boot_sdo,boot_oe,boot_cs,boot_clock_sclk,boot_clock_sda,boot_clock_cs;
 wire boot_done,boot_finished,boot_toggle;wire [111:0] boot_diag;wire [6:0] boot_index;
 tc_boot_config #(.STARTUP_CYCLES(STARTUP_CYCLES),.PLL_WAIT_CYCLES(PLL_WAIT_CYCLES),
  .SPI_HALF_CYCLES(SPI_HALF_CYCLES),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) boot(
  .clk(clk25),.reset(reset),.adc_sdi(adc_sdi),
  .clk_sclk(boot_clock_sclk),.clk_sda(boot_clock_sda),.clk_cs(boot_clock_cs),
  .adc_sclk(boot_sclk),.adc_sda(boot_sdo),.adc_sda_enable(boot_oe),.adc_cs(boot_cs),
  .config_done(boot_done),.config_finished(boot_finished),.diagnostic(boot_diag),
  .diagnostic_toggle(boot_toggle),.config_index(boot_index));
 assign clk_sclk=startup_finished?1'b0:boot_clock_sclk;
 assign clk_sda=startup_finished?1'b0:boot_clock_sda;
 assign clk_cs=startup_finished?1'b1:boot_clock_cs;
 localparam BOOT=0,IDLE=1,ISSUE=2,WAIT_SPI=3,PUBLISH=4;
 reg [2:0] state=BOOT;
 reg selected_mode=1;
 reg boot_verified=0;
 reg [4:0] index=0;
 reg [31:0] watchdog=0;
 reg start=0;
 wire busy,done,sclk,sdo,sdo_enable,cs_n;wire [7:0] read_data;
 wire read_enable=(index==5 || (index>=7 && index<=12) || (index>=14 && index<=16));
 function [23:0] word_at;
  input [4:0] position;input test_mode;
  begin
   case(position)
    0:word_at=24'h000501;
    1:word_at={16'h000d,test_mode?8'h06:8'h00};
    2:word_at=24'h000502;
    3:word_at={16'h000d,test_mode?8'h04:8'h00};
    4:word_at=24'h00ff01;
    5:word_at=24'h800100;
    6:word_at=24'h000501;
    7:word_at=24'h800500;
    8:word_at=24'h801400;
    9:word_at=24'h800d00;
    10:word_at=24'h800b00;
    11:word_at=24'h801600;
    12:word_at=24'h801700;
    13:word_at=24'h000502;
    14:word_at=24'h800500;
    15:word_at=24'h801400;
    16:word_at=24'h800d00;
    17:word_at=24'h000501;
    default:word_at=24'h000501;
   endcase
  end
 endfunction
 spi_rw24 #(.HALF_CYCLES(SPI_HALF_CYCLES)) runtime_spi(
  .clk(clk25),.reset(reset || state==PUBLISH),.start(start),
  .word(word_at(index,selected_mode)),.read_enable(read_enable),.sdi(adc_sdi),
  .busy(busy),.done(done),.sclk(sclk),.sdo(sdo),.sdo_enable(sdo_enable),.cs_n(cs_n),.read_data(read_data));
 assign adc_sclk=startup_finished?sclk:boot_sclk;
 assign adc_sdo=startup_finished?sdo:boot_sdo;
 assign adc_sdo_enable=startup_finished?sdo_enable:boot_oe;
 assign adc_cs=startup_finished?cs_n:boot_cs;
 reg [7:0] id_raw=0,a_format=0,b_format=0,a_test=0,b_test=0;
 reg [7:0] divide_raw=0,phase_raw=0,delay_raw=0,a_index=0,b_index=0;
 reg [7:0] error_code=0,passed=0;
 reg [7:0] expected,mask,check_error;
 always @* begin
  expected=0;mask=8'hff;check_error=0;
  case(index)
   5:begin expected=8'h82;check_error=1;end
   7:begin expected=8'h01;mask=8'h03;check_error=2;end
   8:begin expected=8'h05;mask=8'h17;check_error=3;end
   9:begin expected=selected_mode?8'h06:8'h00;mask=8'h8f;check_error=4;end
   10:begin expected=0;mask=8'h3f;check_error=5;end
   11:begin expected=0;mask=8'ha0;check_error=6;end
   12:begin expected=0;mask=8'h9f;check_error=7;end
   14:begin expected=8'h02;mask=8'h03;check_error=8;end
   15:begin expected=8'h05;mask=8'h17;check_error=9;end
   16:begin expected=selected_mode?8'h04:8'h00;mask=8'h8f;check_error=10;end
   default:begin expected=0;mask=0;check_error=0;end
  endcase
 end
 always @(posedge clk25) begin
  start<=0;
  if(reset)begin
   startup_finished<=0;config_busy<=1;config_verified<=0;active_mode<=0;
   config_epoch<=0;diagnostic<=0;result_toggle<=0;state<=BOOT;selected_mode<=1;boot_verified<=0;
   index<=0;watchdog<=0;error_code<=0;passed<=0;
   id_raw<=0;a_format<=0;b_format<=0;a_test<=0;b_test<=0;
   divide_raw<=0;phase_raw<=0;delay_raw<=0;a_index<=0;b_index<=0;
  end else begin
   if(state==ISSUE || state==WAIT_SPI)watchdog<=watchdog+1'b1;
   if((state==ISSUE || state==WAIT_SPI) && watchdog>=TIMEOUT_CYCLES-1)begin
    error_code<=11;state<=PUBLISH;
   end else case(state)
    BOOT:if(boot_finished)begin
     startup_finished<=1;config_busy<=0;config_verified<=boot_done;boot_verified<=boot_done;
     active_mode<=boot_done?32'h80000001:32'h00000001;
     diagnostic<=boot_diag;config_epoch<=1;result_toggle<=~result_toggle;state<=IDLE;
    end
    IDLE:if(mode_start)begin
     selected_mode<=mode_value;active_mode<={31'b0,mode_value};
     config_busy<=1;config_verified<=0;index<=0;watchdog<=0;error_code<=0;passed<=0;
     id_raw<=0;a_format<=0;b_format<=0;a_test<=0;b_test<=0;
     divide_raw<=0;phase_raw<=0;delay_raw<=0;a_index<=0;b_index<=0;
     // Mode-only writes cannot repair an incomplete clock/ADC boot sequence.
     if(boot_verified)state<=ISSUE;
     else begin error_code<=13;state<=PUBLISH;end
    end
    ISSUE:if(!busy)begin start<=1;state<=WAIT_SPI;end
    WAIT_SPI:if(done)begin
     case(index)
      5:id_raw<=read_data;
      7:a_index<=read_data;
      8:a_format<=read_data;
      9:a_test<=read_data;
      10:divide_raw<=read_data;
      11:phase_raw<=read_data;
      12:delay_raw<=read_data;
      14:b_index<=read_data;
      15:b_format<=read_data;
      16:b_test<=read_data;
     endcase
     if(read_enable && (read_data & mask)!==expected)begin error_code<=check_error;state<=PUBLISH;end
     else begin
      if(read_enable)passed<=passed+1'b1;
      if(index==17)state<=PUBLISH;
      else begin index<=index+1'b1;state<=ISSUE;end
     end
    end
    PUBLISH:begin
     diagnostic<={8'h7d,(error_code==0 && passed==10)?8'ha1:8'he1,passed,error_code,
      b_index,a_index,delay_raw,phase_raw,divide_raw,b_test,a_test,b_format,a_format,id_raw};
     config_verified<=(error_code==0 && passed==10);
     active_mode<={((error_code==0 && passed==10)?1'b1:1'b0),30'b0,selected_mode};
     config_epoch<=(config_epoch==32'hffffffff)?32'd1:config_epoch+1'b1;
     result_toggle<=~result_toggle;config_busy<=0;state<=IDLE;
    end
    default:begin error_code<=12;state<=PUBLISH;config_busy<=1;config_verified<=0;end
   endcase
  end
 end
 wire unused_boot=^{boot_toggle,boot_index};
endmodule
