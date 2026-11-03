`timescale 1ns/1ps
module tb_business_mix;
reg clk=0,axi=0,rst=0;
always #4.069 clk=~clk;
always #5 axi=~axi;
reg [31:0] source0[0:4096],source1[0:4096];
reg [1:0] phase=0;
integer n0=0,n1=0,outputs=0,fd;
wire valid0=phase==0,valid1=phase==2;
wire [31:0] sample0=source0[1+n0],sample1=source1[1+n1];
wire validout;
wire [11:0] oi0,oq0,oi1,oq1;
always @(negedge clk)if(rst)begin
 phase<=phase+1'b1;
 if(valid0 && n0<4095)n0<=n0+1;
 if(valid1 && n1<4095)n1<=n1+1;
end
relay_dq dut(.dq_data_clk(clk),.raxi_clk(axi),.rst_n(rst),.phy_mode(1'b0),
 .adc_d1q1_valid(valid0),.adc_d2q2_valid(valid1),
 .adc_data_d1(sample0[11:0]),.adc_data_q1(sample0[27:16]),
 .adc_data_d2(sample1[11:0]),.adc_data_q2(sample1[27:16]),
 .ctrl_mode(2'd1),.ctrl_mode2(2'd1),.ctrl_dc_en(1'b0),.ctrl_dc_en2(1'b0),
 .ctrl_gain(12'h800),.ctrl_gain2(12'h800),
 .ctrl_ddc_freq(source0[0]),.ctrl_ddc_freq2(source1[0]),.ctrl_duc_freq(32'b0),.ctrl_duc_freq2(32'b0),
 .dac_valid(validout),.dac_data_d1(oi0),.dac_data_q1(oq0),.dac_data_d2(oi1),.dac_data_q2(oq1),
 .status_sample_cnt(),.status_sample_cnt2(),.status_clip_cnt(),.status_clip_cnt2(),.status_out_cnt());
always @(negedge clk) if(rst && validout)begin
 outputs=outputs+1;
 // Skip control CDC/pipeline startup, retain only continuously generated IQ.
 if(outputs>64 && outputs<=4064)$fdisplay(fd,"%08h %08h",{4'b0,oq0,4'b0,oi0},{4'b0,oq1,4'b0,oi1});
 if(outputs==4064)begin $fclose(fd);$display("MIXER_CAPTURE_PASS");$finish;end
end
initial begin
 $readmemh("business_ch0.hex",source0);$readmemh("business_ch1.hex",source1);
 fd=$fopen("mixed_iq.txt","w");
 #100;@(negedge clk);rst=1;
 #1000000;$fatal(1,"timeout");
end
endmodule
