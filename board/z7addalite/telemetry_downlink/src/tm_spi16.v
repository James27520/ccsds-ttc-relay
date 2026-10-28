// AD9122 8-bit instruction + 8-bit data, mode 0, MSB first.
// Derived from telecontrol_system/src/spi_rw24.v (r4c): same CE/turnaround
// scheme, command shortened to 8 bits. sdo_enable=1 means drive SDIO.
module tm_spi16 #(parameter HALF_CYCLES=50)(
 input clk,input reset,input start,input [15:0] word,input read_enable,
 input sdi, output reg busy=0,output reg done=0,output reg fault=0,
 output reg sclk=0,output reg sdo=0,output reg sdo_enable=0,
 output reg cs_n=1,output reg [7:0] read_data=0);
 reg [15:0] shift=0;
 reg [4:0] bit_count=0;
 reg [15:0] divider=0;
 reg finishing=0,reading=0;
 always @(posedge clk) begin
  done<=0;
  if(reset) begin
   busy<=0;cs_n<=1;sclk<=0;sdo<=0;sdo_enable<=0;fault<=0;
   divider<=0;finishing<=0;bit_count<=0;shift<=0;reading<=0;read_data<=0;
  end else if(!busy) begin
   if(start) begin
    busy<=1;cs_n<=0;sclk<=0;sdo<=read_enable ? 1'b1 : word[15];
    shift<={read_enable ? 1'b1 : word[15],word[14:0]};
    sdo_enable<=1;divider<=0;bit_count<=0;finishing<=0;
    reading<=read_enable;fault<=0;
    if(read_enable) read_data<=0;
   end
  end else begin
   // Release one clk after command A0 was captured, before falling SCLK
   // lets AD9122 drive D7. HALF_CYCLES >= 2 is mandatory.
   if(reading && sclk && bit_count==7 && divider==0) sdo_enable<=0;
   if(divider==HALF_CYCLES-1) begin
    divider<=0;
    if(finishing) begin
     cs_n<=1;busy<=0;done<=1;finishing<=0;
     // Leave SDIO high-Z after reads to respect the slave's tDIS.
     sdo_enable<=0;
    end else if(!sclk) begin
     sclk<=1;
     // Pin echo detects a clamped/contended write bus. Readback separately
     // validates the slave, since an open pin echoes our own output.
     if(sdo_enable && (sdi !== sdo)) fault<=1;
     if(reading && bit_count>=8) read_data<={read_data[6:0],sdi};
    end else begin
     sclk<=0;
     if(bit_count==15) finishing<=1;
     else begin bit_count<=bit_count+1'b1;shift<={shift[14:0],1'b0};sdo<=shift[14];end
    end
   end else divider<=divider+1'b1;
  end
 end
endmodule
