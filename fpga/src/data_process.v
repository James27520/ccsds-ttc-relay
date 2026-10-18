`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 2024/05/06 15:25:01
// Design Name: 
// Module Name: data_process
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


module data_process(
//接收数据通道
    input                   rx_clk_in_p,
    input                   rx_clk_in_n,
    input                   rx_frame_in_p,   
    input                   rx_frame_in_n,
    input         [5:0]     rx_data_in_p,
    input         [5:0]     rx_data_in_n,
//发送数据通道  
    output                  tx_clk_out_p,
    output                  tx_clk_out_n,
    output                  tx_frame_out_p,
    output                  tx_frame_out_n,
    output        [5:0]     tx_data_out_p,
    output        [5:0]     tx_data_out_n,
//复位信号  
    input                   reset,
    output                  sample_clk,
//接收数据信号  
    output   reg [11:0]     rx0_i_data,
    output   reg [11:0]     rx0_q_data,
    output   reg [11:0]     rx1_i_data,
    output   reg [11:0]     rx1_q_data,
//发送数据信号  
    input        [11:0]     tx0_i_data,
    input        [11:0]     tx0_q_data,
    input        [11:0]     tx1_i_data,
    input        [11:0]     tx1_q_data
    );
/*****************************采样时钟产生**********************************/
wire data_clk;      //接收时钟的单端信号
CLK_DIV_module#(
    .P_CLK_DIV_CNT                   (4           )         
)
CLK_DIV_module_u0
(
    .i_clk                           (data_clk     ) ,       
    .i_rst                           (reset        ) ,       
    .o_clk_div                       (sample_clk   )         
);

/****************************SELECTIO IO***********************************/
//selectIO输入和输出的数据
wire [13:0] selectio_rx_data;
reg  [13:0] selectio_tx_data;   
//selectIO输出的单端时钟
// wire data_clk;
//物理接口
wire [6:0] selectio_rx_data_in_p;
wire [6:0] selectio_rx_data_in_n;
wire [6:0] selectio_tx_data_out_p;
wire [6:0] selectio_tx_data_out_n;

assign selectio_rx_data_in_p = {rx_frame_in_p,rx_data_in_p};
assign selectio_rx_data_in_n = {rx_frame_in_n,rx_data_in_n};

selectio_wiz_0 selectIO
(
   .data_in_from_pins_p     (selectio_rx_data_in_p),    // input [6:0] data_in_from_pins_p
   .data_in_from_pins_n     (selectio_rx_data_in_n),    // input [6:0] data_in_from_pins_n
   .data_in_to_device       (selectio_rx_data),         // output [13:0] data_in_to_device
   .data_out_from_device    (selectio_tx_data),         // input [13:0] data_out_from_device
   .data_out_to_pins_p      (selectio_tx_data_out_p),   // output [6:0] data_out_to_pins_p
   .data_out_to_pins_n      (selectio_tx_data_out_n),   // output [6:0] data_out_to_pins_n
   .clk_to_pins_p           (tx_clk_out_p),             // output clk_to_pins_p
   .clk_to_pins_n           (tx_clk_out_n),             // output clk_to_pins_n
   .clk_in_p                (rx_clk_in_p),              // input clk_in_p                          
   .clk_in_n                (rx_clk_in_n),              // input clk_in_n
   .clk_out                 (data_clk),                 // output clk_out
   .clk_reset               (reset),                    // input clk_reset
   .io_reset                (reset)                     // input io_reset
); 

//将selectIO输出的差分信号赋值给物理接口
assign tx_frame_out_p = selectio_tx_data_out_p[6];
assign tx_frame_out_n = selectio_tx_data_out_n[6];
assign tx_data_out_p = selectio_tx_data_out_p[5:0];
assign tx_data_out_n = selectio_tx_data_out_n[5:0];

/*******************************接收数据解包***************************************/
//Frame信号
wire rx_frame;
reg rx_frame_d;
assign rx_frame = selectio_rx_data[13];
//接收到的数据,分组
reg [5:0] rx0_msb_i;
reg [5:0] rx0_msb_q;
reg [5:0] rx0_lsb_i;
reg [5:0] rx0_lsb_q;	
reg [5:0] rx1_msb_i;
reg [5:0] rx1_msb_q;	
reg [5:0] rx1_lsb_i;
reg [5:0] rx1_lsb_q;
//frame信号打拍
always @(posedge data_clk or posedge reset) begin
    if(reset)
        rx_frame_d <= 0;
    else 
        rx_frame_d <= rx_frame;
end	
//数据解析，对selectIO输出的数据进行解包
always @(posedge data_clk or posedge reset) begin
    if(reset) begin
        rx0_msb_i<=0;
        rx0_msb_q<=0;
        rx0_lsb_i<=0;
        rx0_lsb_q<=0;
        rx1_msb_i<=0;
        rx1_msb_q<=0;
        rx1_lsb_i<=0;
        rx1_lsb_q<=0;			
    end 
    else if(rx_frame_d==0 && rx_frame==1) begin
        rx0_msb_i <= selectio_rx_data[05:0];
        rx0_msb_q <= selectio_rx_data[12:7];
    end 
    else if(rx_frame_d==1 && rx_frame==1) begin
        rx0_lsb_i <= selectio_rx_data[05:0];
        rx0_lsb_q <= selectio_rx_data[12:7];
    end 
    else if(rx_frame_d==1 && rx_frame==0) begin
        rx1_msb_i <= selectio_rx_data[05:0];
        rx1_msb_q <= selectio_rx_data[12:7];
    end 
    else if(rx_frame_d==0 && rx_frame==0) begin
        rx1_lsb_i <= selectio_rx_data[05:0];
        rx1_lsb_q <= selectio_rx_data[12:7];
    end	
end
//对采样寄存的信号组合
reg [11:0] rx0_q_data_r;
reg [11:0] rx0_i_data_r;
reg [11:0] rx1_q_data_r;
reg [11:0] rx1_i_data_r;
always @(posedge data_clk or posedge reset) begin
    if(reset) begin
        rx0_q_data_r <= 'd0;
        rx0_i_data_r <= 'd0;
        rx1_q_data_r <= 'd0;
        rx1_i_data_r <= 'd0;			
    end 
    else if(rx_frame_d==0 && rx_frame==1) begin
        rx0_q_data_r = {rx0_msb_q,rx0_lsb_q};
        rx0_i_data_r = {rx0_msb_i,rx0_lsb_i};
        rx1_q_data_r = {rx1_msb_q,rx1_lsb_q};
        rx1_i_data_r = {rx1_msb_i,rx1_lsb_i};
    end 
    else begin
        rx0_q_data_r = rx0_q_data_r;
        rx0_i_data_r = rx0_i_data_r;
        rx1_q_data_r = rx1_q_data_r;
        rx1_i_data_r = rx1_i_data_r;
    end	
end

//打拍同步到采样时钟
always @(posedge sample_clk) begin
    rx0_q_data = rx0_q_data_r;
    rx0_i_data = rx0_i_data_r;
    rx1_q_data = rx1_q_data_r;
    rx1_i_data = rx1_i_data_r;
end
/*******************************发送数据打包***************************************/
//需要发送的数据，分组
reg [5:0] tx0_msb_i;
reg [5:0] tx0_msb_q;
reg [5:0] tx0_lsb_i;
reg [5:0] tx0_lsb_q;
reg [5:0] tx1_msb_i;
reg [5:0] tx1_msb_q;
reg [5:0] tx1_lsb_i;
reg [5:0] tx1_lsb_q;


always @(posedge data_clk or posedge reset) begin
    if(reset) begin
        tx0_msb_i <= 'd0;
        tx0_msb_q <= 'd0;
        tx0_lsb_i <= 'd0;
        tx0_lsb_q <= 'd0;
        tx1_msb_i <= 'd0;
        tx1_msb_q <= 'd0;
        tx1_lsb_i <= 'd0;
        tx1_lsb_q <= 'd0;
    end
    else if(tx_frame_d==0 && tx_frame==0) begin
        tx0_msb_i <= tx0_i_data[11:6];
        tx0_msb_q <= tx0_q_data[11:6];
        tx0_lsb_i <= tx0_i_data[5:0];
        tx0_lsb_q <= tx0_q_data[5:0];
        tx1_msb_i <= tx1_i_data[11:6];
        tx1_msb_q <= tx1_q_data[11:6];
        tx1_lsb_i <= tx1_i_data[5:0];
        tx1_lsb_q <= tx1_q_data[5:0];
    end
    else begin
        tx0_msb_i <= tx0_msb_i;
        tx0_msb_q <= tx0_msb_q;
        tx0_lsb_i <= tx0_lsb_i;
        tx0_lsb_q <= tx0_lsb_q;
        tx1_msb_i <= tx1_msb_i;
        tx1_msb_q <= tx1_msb_q;
        tx1_lsb_i <= tx1_lsb_i;
        tx1_lsb_q <= tx1_lsb_q;
    end
end

//用于产生tx_frame
reg tx_frame;
reg tx_frame_d;
reg [1:0] data_clk_count;
always @(posedge data_clk or posedge reset) begin
    if(reset) begin
        data_clk_count <= 0;
    end else begin
        data_clk_count <= data_clk_count + 1;
    end
end	
//产生frame
always @(posedge data_clk or posedge reset) begin
    if(reset) begin
        tx_frame <= 0;
    end else if(data_clk_count==2'b00) begin
        tx_frame <= 1;
    end else if(data_clk_count==2'b10) begin
        tx_frame <= 0;
    end
end
//frame信号打拍
always @(posedge data_clk or posedge reset) begin
    if(reset)
        tx_frame_d <= 0;
    else
        tx_frame_d <= tx_frame;
end	
//在固定位置输出数据给selectIO
always @(posedge data_clk or posedge reset) begin
    if(reset)
        selectio_tx_data <= 'd0;
    else if(tx_frame_d==0 && tx_frame==1)
        selectio_tx_data <= {tx_frame,tx0_msb_q,tx_frame,tx0_msb_i};
    else if(tx_frame_d==1 && tx_frame==1)
        selectio_tx_data <= {tx_frame,tx0_lsb_q,tx_frame,tx0_lsb_i};
    else if(tx_frame_d==1 && tx_frame==0)
        selectio_tx_data <= {tx_frame,tx1_msb_q,tx_frame,tx1_msb_i};
    else if(tx_frame_d==0 && tx_frame==0)
        selectio_tx_data <= {tx_frame,tx1_lsb_q,tx_frame,tx1_lsb_i};		
end	


endmodule
