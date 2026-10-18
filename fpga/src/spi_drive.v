`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date: 2024/04/18 12:43:20
// Design Name: 
// Module Name: spi_drive
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


module spi_drive#(
    parameter                   P_DATA_WIDTH    = 8 ,
    parameter                   P_CPOL          = 0 ,
    parameter                   P_CPHA          = 0 
)(
    input                       i_clk               ,
    input                       i_rst               ,

    output                      o_spi_clk           ,
    output                      o_spi_cs            ,
    output                      o_spi_mosi          ,
    input                       i_spi_miso          ,

    input   [P_DATA_WIDTH-1:0]  i_user_data         ,
    input                       i_user_valid        ,
    output                      o_user_ready        ,

    output  [P_DATA_WIDTH-1:0]  o_user_read_data    ,
    output                      o_user_read_valid   
);

/*********************function**************************/

/*********************parameter*************************/

/***********************port****************************/

/***********************mechine*************************/

/************************reg****************************/
reg                             ro_spi_clk           ;
reg                             ro_spi_cs            ;
reg                             ro_spi_mosi          ;
reg                             ro_user_ready        ;
reg     [P_DATA_WIDTH-1:0]      r_user_data          ;
reg                             r_run                ;
reg     [15:0]                  r_cnt                ;
reg                             r_spi_cnt            ;

reg                             ro_user_read_valid   ;
reg     [P_DATA_WIDTH-1:0]      ro_user_read_data    ;

reg                             r_run_d              ;
/************************wire***************************/
wire                            w_user_active        ;
/*********************component*************************/

/***********************assign**************************/
assign  o_spi_clk           = ro_spi_clk                    ;
assign  o_spi_cs            = ro_spi_cs                     ;
assign  o_spi_mosi          = ro_spi_mosi                   ;
assign  o_user_ready        = ro_user_ready                 ;
assign  o_user_read_data    = ro_user_read_data             ;
assign  o_user_read_valid   = ro_user_read_valid            ;
assign  w_user_active       = i_user_valid & o_user_ready   ;

/***********************always**************************/
always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        r_user_data <= 'd0;
    else if(w_user_active)
        r_user_data <= i_user_data;
    else if(r_spi_cnt)
        r_user_data <= r_user_data << 1;
    else
        r_user_data <= r_user_data;
end

always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        ro_user_ready <= 'd1;
    else if(w_user_active)
        ro_user_ready <= 'd0;
    else if(!r_run && r_run_d)
        ro_user_ready <= 'd1;
    else 
        ro_user_ready <= ro_user_ready;
end

always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        r_run_d <= 'd0;
    else 
        r_run_d <= r_run;
end


always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        r_run <= 'd0;
    else if(r_spi_cnt && r_cnt >= P_DATA_WIDTH - 1)
        r_run <= 'd0;
    else if(w_user_active)
        r_run <= 'd1;
    else
        r_run <= r_run;
end

always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        r_cnt <= 'd0;
    else if(r_spi_cnt && r_cnt >= P_DATA_WIDTH - 1)
        r_cnt <= 'd0;
    else if(r_spi_cnt)
        r_cnt <= r_cnt + 1;
    else
        r_cnt <= r_cnt;
end
 
always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        r_spi_cnt <= 'd0;
    else if(r_run)
        r_spi_cnt <= r_spi_cnt + 1;
    else
        r_spi_cnt <= 'd0;
end


always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        ro_spi_clk <= P_CPOL;
    else if(r_run)
        ro_spi_clk <= ~ro_spi_clk;
    else
        ro_spi_clk <= P_CPOL;
end

always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        ro_spi_cs <= 'd1;
    else if(w_user_active)
        ro_spi_cs <= 'd0;
    else if(!r_run)
        ro_spi_cs <= 'd1;
    else
        ro_spi_cs <= ro_spi_cs;
end

always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        ro_spi_mosi <= 'd0;
    else if(w_user_active)
        ro_spi_mosi <= i_user_data[P_DATA_WIDTH-1];
    else if(r_spi_cnt && P_CPHA==0 && r_run)
        ro_spi_mosi <= r_user_data[P_DATA_WIDTH-2];
    else if(!r_spi_cnt && P_CPHA==1 && r_run)
        ro_spi_mosi <= r_user_data[P_DATA_WIDTH-1];
    else
        ro_spi_mosi <= ro_spi_mosi;
end


always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        ro_user_read_data <= 'd0;
    else if(!r_spi_cnt && P_CPHA==0 && r_run)
        ro_user_read_data <= {ro_user_read_data[P_DATA_WIDTH - 2:0],i_spi_miso}; 
    else if(r_spi_cnt && P_CPHA==1  && r_run)
       ro_user_read_data <= {ro_user_read_data[P_DATA_WIDTH - 2:0],i_spi_miso}; 
    else
       ro_user_read_data <= ro_user_read_data;         
end

always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        ro_user_read_valid <= 'd0;
    else if(r_spi_cnt && r_cnt == P_DATA_WIDTH - 1)
        ro_user_read_valid <= 'd1;       
    else
        ro_user_read_valid <= 'd0;
end

endmodule
