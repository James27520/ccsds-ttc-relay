`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 2023/09/08 13:17:48
// Design Name: 
// Module Name: DDS
// Project Name: 
// Target Devices: 
// Tool Versions: 
// Description: 
// 
// Dependencies: 
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
//////////////////////////////////////////////////////////////////////////////////

module DDS
#(  parameter [31:0] CLK_Freq = 125_000_000,
    parameter [63:0] Out_Freq_mHz = 1000_000_000,
    parameter [31:0] Pword = 0
    )
    (
    input   wire        		clk,                            //时钟
	input   wire        		reset_n,                        //复位信号
	output  wire        [11:0]  sine_out                 		//输出数据
);


//初始参数
parameter [95:0] Fword = {Out_Freq_mHz[63:0],32'b0}/CLK_Freq/1000;               //相位累加器自加值
//parameter [95:0] Fword = 171_798_692;               //相位累加器自加值



//相位累加器模块
reg [31:0] Fcnt;                        //相位累加器
always @(posedge clk or negedge reset_n)
   begin
	if(!reset_n)
		Fcnt <= 32'd0;                  //Fcnt：相位累加器，Fcnt是一个32位数字；
	else
		Fcnt <= Fcnt + Fword;           //每次时钟tik，Fcnt总是步进Fword次；
   end


//ROM读取数据
wire [11:0]rom_addr;                     //ROM地址  
assign rom_addr = Fcnt[31:20] + Pword;   //赋值ROM数据读取地址
//根据地址从ROM中读取数据输出
wire [11:0] wave_data;                  //从ROM读出的波形数据
wire [11:0] signed_wave_data;
assign signed_wave_data = wave_data[11] ? (wave_data - 2048) : {2048 - wave_data};
blk_mem_gen_0 rom(
	.addra(rom_addr),
	.clka(clk),
	.douta(wave_data)
	);
//波形数据缓冲 
reg signed[11:0] wave_data_r;

always @(posedge clk)
begin
	wave_data_r <= wave_data[11] ? signed_wave_data : {1'b1,signed_wave_data[10:0]};
end

assign sine_out = wave_data_r[11] ? {1'b1,~wave_data_r[10:0]+1} : wave_data_r;




endmodule
