// SPI mode 0, 16-bit instruction + 8-bit data, MSB first; clk-enable only.
// read_enable is latched at accepted start. A read forces command word[23]=1.
// Writes preserve the original spi_write24 SCLK/CS/SDO waveform exactly.
// For writes caller must supply a genuine write command (word[23] == 0).
// IOBUF: I=sdo, T=~sdo_enable, O=sdi. No internal tri-state or divided clock.
// HALF_CYCLES must be >=2: leave a full clk of command hold before releasing
// SDIO, and release BEFORE the falling edge that lets the slave drive D7.
module spi_rw24 #(parameter HALF_CYCLES=50)(
 input clk,input reset,input start,input [23:0] word,input read_enable,
 input sdi,
 output reg busy=0,output reg done=0,
 output reg sclk=0,output reg sdo=0,output reg sdo_enable=0,output reg cs_n=1,
 output reg [7:0] read_data=0);

 reg [23:0] shift=0;
 reg [5:0] bit_count=0;
 reg [15:0] divider=0;
 reg finishing=0;
 reg reading=0;

 always @(posedge clk) begin
  done<=0;
  if(reset) begin
   busy<=0;cs_n<=1;sclk<=0;sdo<=0;sdo_enable<=0;
   divider<=0;finishing<=0;bit_count<=0;shift<=0;reading<=0;read_data<=0;
  end else if(!busy) begin
   if(start) begin
    busy<=1;cs_n<=0;sclk<=0;sdo<=(read_enable ? 1'b1 : word[23]);
    shift<={read_enable ? 1'b1 : word[23],word[22:0]};
    sdo_enable<=1;divider<=0;bit_count<=0;finishing<=0;
    reading<=read_enable;
    // Hold previous read_data during writes; clear only at a new read/reset.
    if(read_enable) read_data<=0;
   end
  end else begin
   // Sixteenth rising SCLK has already captured instruction bit0. At this
   // next clk, hold has lasted one clk (40 ns at clk25). Disable before the
   // sixteenth falling edge; the slave may drive immediately on that edge.
   if(reading && sclk && bit_count==15 && divider==0) sdo_enable<=0;
   if(divider==HALF_CYCLES-1) begin
    divider<=0;
    if(finishing) begin
     cs_n<=1;busy<=0;done<=1;finishing<=0;
     // Keep read direction high-Z after CS rises, throughout idle. Never
     // reacquire SDIO here: the slave can retain its output during tDIS.
    end else if(!sclk) begin
     sclk<=1;
     if(reading && bit_count>=16) read_data<={read_data[6:0],sdi};
    end else begin
     sclk<=0;
     if(bit_count==23) finishing<=1;
     else begin bit_count<=bit_count+1'b1;shift<={shift[22:0],1'b0};sdo<=shift[22];end
    end
   end else divider<=divider+1'b1;
  end
 end
endmodule
