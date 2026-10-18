module AD936X_Init#
(
    parameter           SPI_CLK_FREQ = 25
)
    (
	input 				i_clk       ,
	input 				i_rst       ,
    output              o_spi_clk   , 
    output              o_spi_cs    , 
    output              o_spi_mosi  ,
    input               i_spi_miso  ,
	output	reg			chip_rst_n  ,
	output 	reg			init_done
);


/*********************function**************************/	
`include "AD936X_lut.v"
always @ (posedge i_clk)	command <= ad9361_lut(index);
/*********************parameter*************************/
localparam              P_ST_IDLE   =   0,
                        P_ST_LUT    =   1,
                        P_ST_SPI    =   2,
                        P_ST_CHECK  =   3,
                        P_ST_ADD    =   4,
                        P_ST_WAIT1  =   5,
                        P_ST_WAIT2  =   6,
                        P_ST_END    =   7;
/***********************port****************************/

/***********************mechine*************************/
reg	   [7:0]	st_current  ;       
reg    [7:0]     st_next     ;
reg    [15:0]    r_st_cnt    ;

always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        st_current <= P_ST_IDLE;
    else
        st_current <= st_next;
end

always @(*) begin
    case(st_current)
        P_ST_IDLE   : st_next <= r_st_cnt >=  SPI_CLK_FREQ * 1000   ? P_ST_LUT : P_ST_IDLE ;
        P_ST_LUT    : st_next <= w_active                           ? P_ST_SPI : P_ST_LUT  ;      
        P_ST_SPI    : st_next <= o_user_read_valid                  ? ~command[18] ? P_ST_CHECK : P_ST_ADD : P_ST_SPI  ;
        P_ST_CHECK  :
                    case(command)   
                                {1'b0,10'h037,8'h08}:   begin if( readdata[3])         st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //ReadPartNumber   		
                                {1'b0,10'h05E,8'h80}:   begin if( readdata[7])         st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //BBPLL_INDEX  			
                                {1'b0,10'h244,8'h80}:   begin if( readdata[7])         st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //RX_CPCAL_INDEX  		
                                {1'b0,10'h284,8'h80}:   begin if( readdata[7])         st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //TX_CPCAL_INDEX  		
                                {1'b0,10'h247,8'h02}:   begin if( readdata[1])         st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //RX_PLL_LOCK_INDEX 		
                                {1'b0,10'h287,8'h02}:   begin if( readdata[1])         st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //TX_PLL_LOCK_INDEX 		
                                {1'b0,10'h016,8'h80}:   begin if(!readdata[7])         st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //RX_FIR_TUNE_INDEX 		
                                {1'b0,10'h016,8'h40}:   begin if(!readdata[6])         st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //TX_FIR_TUNE_INDEX 		
                                {1'b0,10'h016,8'h01}:   begin if(!readdata[0])         st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //BBDC_OFFSET_CAL_INDEX 	
                                {1'b0,10'h016,8'h02}:   begin if(!readdata[1])         st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //RFDC_OFFSET_CAL_INDEX	
                                {1'b0,10'h016,8'h10}:   begin if(!readdata[4])         st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //TX_QUAD_CAL_INDEX		
                                {1'b0,10'h016,8'h20}:   begin if(!readdata[5])         st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //RX_QUAD_CAL_INDEX	
                                {1'b0,10'h017,8'h1A}:   begin if(readdata[3:0]==4'd10) st_next <= P_ST_ADD;else st_next <= P_ST_LUT;end         //RX_QUAD_CAL_INDEX	
                                {1'b0,10'h3FF,8'h01}:   st_next <= r_st_cnt >= SPI_CLK_FREQ * 1000               ? P_ST_ADD : P_ST_CHECK ;		    //wait 1msd
                                {1'b0,10'h3FF,8'h14}:   st_next <= r_st_cnt >= SPI_CLK_FREQ * 2000               ? P_ST_ADD : P_ST_CHECK ;            //wait 20ms	  	  														
                                {1'b0,10'h3FF,8'hFF}:   st_next <= P_ST_END;                							                        //command end
                                default:                st_next <= P_ST_ADD;
                    endcase
        P_ST_ADD    : st_next <= P_ST_WAIT1;   
        P_ST_WAIT1  : st_next <= P_ST_WAIT2;
        P_ST_WAIT2  : st_next <= P_ST_LUT;
        P_ST_END    : st_next <= P_ST_END;
        default     : st_next <= P_ST_IDLE;
    endcase 
end

/************************reg****************************/
reg	       [12:0]	            index       ;       //初始化参数索引
reg         [18:0]	            command     ;       //配置参数命令
reg         [7:0]                readdata   ;       //读出的8位数据
/************************wire***************************/
wire                            w_active;            //SPI总线激活信号
reg         [23:0]              i_user_data ;        //SPI写数据信号
reg                             i_user_valid;        //SPI写有效信号
wire                            o_user_ready;        //SPI驱动准备好信号
wire        [23:0]              o_user_read_data;    //读出数据
wire                            o_user_read_valid;   //读出数据有效信号
/*********************component*************************/
/*****SPI驱动*****/
spi_drive#(
    .P_DATA_WIDTH               (24)                ,
    .P_CPOL                     (0)                 ,
    .P_CPHA                     (1) 
)
spi_drive_U0
(
    .i_clk                      (i_clk),
    .i_rst                      (i_rst),

    .o_spi_clk                  (o_spi_clk ),
    .o_spi_cs                   (o_spi_cs  ),
    .o_spi_mosi                 (o_spi_mosi),
    .i_spi_miso                 (i_spi_miso),

    .i_user_data                (i_user_data ),
    .i_user_valid               (i_user_valid),
    .o_user_ready               (o_user_ready),

    .o_user_read_data           (o_user_read_data ),
    .o_user_read_valid          (o_user_read_valid)
);
/***********************assign**************************/
assign w_active     = o_user_ready & i_user_valid;
/***********************always**************************/

/*****状态机计数器*****/
always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        r_st_cnt <= 'd0;
    else if(st_current != st_next)
        r_st_cnt <= 'd0;
    else if(st_current < P_ST_END)
        r_st_cnt <= r_st_cnt + 1;
end

/*****复位信号控制*****/
always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        chip_rst_n <= 'd0;
    else if(st_current == P_ST_IDLE)
        chip_rst_n <= 'd0;
    else
        chip_rst_n <= 'd1;
end

/*****写数据信号控制*****/
assign w_active = o_user_ready & i_user_valid;
always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)begin
        i_user_data  <= 'd0;
        i_user_valid <= 'd0;
    end
    else if(w_active)begin
        i_user_data  <= 'd0;
        i_user_valid <= 'd0;    
    end
    else if(st_current == P_ST_LUT && o_user_ready && command[18]==1)begin  //写操作
            i_user_data <= {command[18],3'b000,2'b00,command[17:0]};
            i_user_valid <= 'd1;
    end  
    else if(st_current == P_ST_LUT && o_user_ready && command[18]==0)begin  //读操作
            i_user_data <= {command[18],3'b000,2'b00,command[17:8],8'd0};
            i_user_valid <= 'd1;
    end   
    else begin
        i_user_data  <= i_user_data ;
        i_user_valid <= i_user_valid;         
    end
end
/*****读数据控制*****/
always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        readdata <= 'd0;
    else if(st_current == P_ST_SPI && o_user_read_valid)
        readdata <= o_user_read_data[7:0];
    else 
        readdata <= readdata;
end
/*****配置命令索引控制*****/
always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        index <= 'd0;
    else if(st_current == P_ST_ADD)
        index <= index + 1;
    else 
        index <= index;
end

/*****初始化完成信号*****/
always @(posedge i_clk or posedge i_rst) begin
    if(i_rst)
        init_done <= 'd0;
    else if(st_current == P_ST_END)
        init_done <= 'd1;
    else 
        init_done <= init_done;
end

endmodule