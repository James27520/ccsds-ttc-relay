module AD936X_Driver (
//接收数据通道
    input               rx_clk_in_p,
    input               rx_clk_in_n,
    input               rx_frame_in_p,   
    input               rx_frame_in_n,
    input               [5:0] rx_data_in_p,
    input               [5:0] rx_data_in_n,
//发送数据通道
    output              tx_clk_out_p,
    output              tx_clk_out_n,
    output              tx_frame_out_p,
    output              tx_frame_out_n,
    output              [5:0] tx_data_out_p,
    output              [5:0] tx_data_out_n,
//输出数据时钟
    output              data_clk,
//ADC数据接口与接收测试信号
    output reg          adc_valid,
    output reg          [11:0] adc_data_i1,
    output reg          [11:0] adc_data_q1,
    output reg          [11:0] adc_data_i2,
    output reg          [11:0] adc_data_q2,
    output reg          adc_status,
    input               adc_r1_mode,  
//DAC数据接口
    input               dac_valid,
    input [11:0]        dac_data_i1,
    input [11:0]        dac_data_q1,
    input [11:0]        dac_data_i2,
    input [11:0]        dac_data_q2,
    input               dac_r1_mode,
    output [3:0]        rx_frame_s,
    output reg     [1:0]tx_data_cnt
);

//输入时钟转单端
wire data_clk_ibuff;


/*****接收数据寄存*****/
reg [ 5:0]  rx_data_n_s_d   = 'd0;
reg         rx_frame_n_s_d  = 'd0;
reg [11:0]  rx_data         = 'd0;
reg [ 1:0]  rx_frame        = 'd0;
reg [11:0]  rx_data_d       = 'd0;
reg [ 1:0]  rx_frame_d      = 'd0;

/*****接收数据接口寄存器*****/
reg         rx_error_r1     = 'd0;
reg         rx_valid_r1     = 'd0;
reg         rx_error_r2     = 'd0;
reg         rx_valid_r2     = 'd0;
reg signed[11:0]  rx_data_i_r1    = 'd0;
reg signed[11:0]  rx_data_q_r1    = 'd0;
reg signed[11:0]  rx_data_i1_r2   = 'd0;
reg signed[11:0]  rx_data_q1_r2   = 'd0;
reg signed[11:0]  rx_data_i2_r2   = 'd0;
reg signed[11:0]  rx_data_q2_r2   = 'd0;

/****发送赋值数据接口*****/
reg         tx_frame      = 'd0;
reg [ 5:0]  tx_data_p     = 'd0;
reg [ 5:0]  tx_data_n     = 'd0;


// reg [ 2:0]  tx_data_cnt   = 'd0;
reg [11:0]  tx_data_i1_d  = 'd0;
reg [11:0]  tx_data_q1_d  = 'd0;
reg [11:0]  tx_data_i2_d  = 'd0;
reg [11:0]  tx_data_q2_d  = 'd0;

wire    [ 2:0]  tx_data_sel_s;
// wire
wire    [ 5:0]  rx_data_ibuf;
wire            rx_frame_ibuf;
wire    [ 5:0]  tx_data_oddr;
wire            tx_frame_oddr;
wire            tx_clk_oddr;

//data_clk双边沿采样数据
// wire    [ 3:0]  rx_frame_s;
wire    [ 5:0]  rx_data_p_s;
wire    [ 5:0]  rx_data_n_s;
wire            rx_frame_p_s;
wire            rx_frame_n_s;

genvar          l_inst;

//接收数据时钟经过BUFG作为驱动时钟
IBUFDS IBUFDS_data_clk_inst (
    .O          (data_clk_ibuff),  
    .I          (rx_clk_in_p),    
    .IB         (rx_clk_in_n)   
);
BUFGCE BUFGCE_data_clk_inst (
    .O          (data_clk),  
    .CE         (1'b1 ), 
    .I          (data_clk_ibuff) 
);

//采样帧数据打拍寄存
assign rx_frame_s = {rx_frame_d, rx_frame};
always @ (posedge data_clk)begin
    rx_frame_n_s_d  <= rx_frame_n_s;
    rx_frame_d      <= rx_frame;  
    rx_frame        <= {rx_frame_n_s_d,rx_frame_p_s};
end

//采样数据打拍寄存
always @ (posedge data_clk)begin
    rx_data_n_s_d   <= rx_data_n_s;
    rx_data_d       <= rx_data;
    rx_data         <= {rx_data_n_s_d,rx_data_p_s};
end

//单个RF的接收数据路径，预计帧仅符合I/Q MSB
always @ (posedge data_clk)
begin
    rx_error_r1 <= ((rx_frame_s==4'b1100)||(rx_frame_s==4'b0011)) ? 1'b0:1'b1;
    rx_valid_r1 <= (rx_frame_s==4'b1100) ? 1'b1:1'b0;
    if (rx_frame_s==4'b1100)
        begin
            rx_data_i_r1 <= {rx_data_d[11:6],rx_data[11:6]};
            rx_data_q_r1 <= {rx_data_d[ 5:0],rx_data[ 5:0]};
        end
end

//双rf的接收数据路径，预计帧仅适用于rf-1的i/q msb和lsb（采用的这个√）
always @ (posedge data_clk)
begin
    rx_error_r2<=((rx_frame_s==4'b1111)||(rx_frame_s==4'b1100)||(rx_frame_s==4'b0000)||(rx_frame_s== 4'b0011)) ? 1'b0 : 1'b1;
    rx_valid_r2<=(rx_frame_s==4'b0000) ? 1'b1 : 1'b0;
    if(rx_frame_s==4'b1111)
        begin
            rx_data_i1_r2 <= {rx_data_d[11:6],rx_data[11:6]};
            rx_data_q1_r2 <= {rx_data_d[ 5:0],rx_data[ 5:0]};
        end
    if(rx_frame_s==4'b0000)
        begin
            rx_data_i2_r2 <= {rx_data_d[11:6],rx_data[11:6]};
            rx_data_q2_r2 <= {rx_data_d[ 5:0],rx_data[ 5:0]};
        end
end

//根据接收模式选择输出的数据

always @ (posedge data_clk)
begin
    if(adc_r1_mode == 1'b1)
        begin
            adc_valid   <= rx_valid_r1;
            adc_data_i1 <= rx_data_i_r1;
            adc_data_q1 <= rx_data_q_r1;
            adc_data_i2 <= 12'd0;
            adc_data_q2 <= 12'd0;
            adc_status  <= ~rx_error_r1;
        end
    else
        begin
            adc_valid   <= rx_valid_r2;
            adc_data_i1 <= rx_data_i1_r2;
            adc_data_q1 <= rx_data_q1_r2;
            adc_data_i2 <= rx_data_i2_r2;
            adc_data_q2 <= rx_data_q2_r2;
            adc_status  <= ~rx_error_r2;
        end
end  

 /*
  tx_data_sel_s：00000	1001	1010	1011	0000	 
  tx_data_cnt：  0000	101	    110	    111	    000
  */
assign tx_data_sel_s = {dac_r1_mode, tx_data_cnt[1:0]};
always @ (posedge data_clk)begin
    tx_data_cnt <= tx_data_cnt + 1;
    case (tx_data_sel_s)
        4'b1101:
        begin
            tx_frame  <= 1'b0;
            tx_data_p <= tx_data_i1_d[ 5:0];
            tx_data_n <= tx_data_q1_d[ 5:0];
        end
        4'b1100:
        begin
            tx_frame  <= 1'b1;
            tx_data_p <= tx_data_i1_d[11:6];
            tx_data_n <= tx_data_q1_d[11:6];
        end
        4'b1011:
        begin
            tx_frame  <= 1'b0;
            tx_data_p <= tx_data_i2_d[ 5:0];
            tx_data_n <= tx_data_q2_d[ 5:0];
        end
        4'b1010:
        begin
            tx_frame  <= 1'b0;
            tx_data_p <= tx_data_i2_d[11:6];
            tx_data_n <= tx_data_q2_d[11:6];
        end
        4'b1001:
        begin
            tx_frame  <= 1'b1;
            tx_data_p <= tx_data_i1_d[ 5:0];
            tx_data_n <= tx_data_q1_d[ 5:0];
        end
        4'b1000:
        begin
            tx_frame  <= 1'b1;
            tx_data_p <= tx_data_i1_d[11:6];
            tx_data_n <= tx_data_q1_d[11:6];
        end
        default:
        begin
            tx_frame  <= 1'b0;
            tx_data_p <= 6'd0;
            tx_data_n <= 6'd0;
        end
    endcase
end

always @ (posedge tx_frame)begin
    if(dac_valid)begin
        tx_data_i1_d <= dac_data_i1;
        tx_data_q1_d <= dac_data_q1;
        tx_data_i2_d <= dac_data_i2;
        tx_data_q2_d <= dac_data_q2;
        tx_data_cnt  <= tx_data_cnt + 1'b1;
    end
    else begin
        tx_data_i1_d <= 'd0;
        tx_data_q1_d <= 'd0;
        tx_data_i2_d <= 'd0;
        tx_data_q2_d <= 'd0;
    end
end   
   


//接收数据差分转单端，IDDR采样
generate
for (l_inst=0;l_inst<=5;l_inst=l_inst+1)
begin:g_rx_data
    IBUFDS i_rx_data_ibuf(       
        .I          (rx_data_in_p[l_inst]),
        .IB         (rx_data_in_n[l_inst]),
        .O          (rx_data_ibuf[l_inst])
    );
    
    IDDR #(
        .DDR_CLK_EDGE("OPPOSITE_EDGE"), 
        .INIT_Q1    (1'b0),             
        .INIT_Q2    (1'b0),             
        .SRTYPE ("SYNC")             
    )     
    i_rx_data_iddr  ( 
        .R            (1'b0                     ),  
        .S            (1'b0                     ),   
        .C            (data_clk                 ),
        .CE           (1'b1                     ),
        .D            (rx_data_ibuf[l_inst]     ),
        .Q1           (rx_data_p_s[l_inst]      ),
        .Q2           (rx_data_n_s[l_inst]      )
    );
end endgenerate    

//接收帧时钟差分转单端，IDDR采样
IBUFDS i_rx_frame_ibuf (
    .I              (rx_frame_in_p),
    .IB             (rx_frame_in_n),
    .O              (rx_frame_ibuf)
);

IDDR #(
    .DDR_CLK_EDGE   ("OPPOSITE_EDGE"), 
    .INIT_Q1        (1'b0),             
    .INIT_Q2        (1'b0),             
    .SRTYPE         ("SYNC")             
)
i_rx_frame_iddr ( 
    .R              (1'b0                   ),
    .S              (1'b0                   ), 
    .CE             (1'b1                   ),
    .C              (data_clk               ),
    .D              (rx_frame_ibuf          ),
    .Q1             (rx_frame_p_s           ),
    .Q2             (rx_frame_n_s           )
);

//发送数据ODDR转换输出
generate
for (l_inst=0;l_inst<=5;l_inst=l_inst+1)
begin: g_tx_data
    ODDR #(
        .DDR_CLK_EDGE("OPPOSITE_EDGE"), 
        .INIT(1'b0),                    
        .SRTYPE("SYNC")                 
    )
    i_tx_data_oddr  (      
    .R              (1'b0                   ),
    .S              (1'b0                   ),
    .CE             (1'b1                   ), 
    .C              (data_clk               ),
    .D1             (tx_data_p[l_inst]      ),
    .D2             (tx_data_n[l_inst]      ),
    .Q              (tx_data_oddr[l_inst]   ));
    OBUFDS i_tx_data_obuf (
        .I          (tx_data_oddr[l_inst]),
        .O          (tx_data_out_p[l_inst]),
        .OB         (tx_data_out_n[l_inst])
    );
end endgenerate


//帧时钟ODDR转换输出
ODDR #(
    .DDR_CLK_EDGE("OPPOSITE_EDGE"),  
    .INIT(1'b0),                     
    .SRTYPE("SYNC")                  
) 
i_tx_frame_oddr (
    .R              (1'b0                   ),
    .S              (1'b0                   ),
    .CE             (1'b1                   ),
    .C              (data_clk               ),
    .D1             (tx_frame               ),
    .D2             (tx_frame               ),
    .Q              (tx_frame_oddr          ));
OBUFDS i_tx_frame_obuf (
    .I              (tx_frame_oddr),
    .O              (tx_frame_out_p),
    .OB             (tx_frame_out_n)
);

// DAC时钟ODDR转换，直接由data_clk决定
ODDR #(
    .DDR_CLK_EDGE("OPPOSITE_EDGE"),   
    .INIT(1'b0),                      
    .SRTYPE("SYNC")                   
)
i_tx_clk_oddr   (
    .R              (1'b0                   ),
    .S              (1'b0                   ),
    .CE             (1'b1                   ),
    .C              (data_clk               ),
    .D1             (1'b0                   ),
    .D2             (1'b1                   ),
    .Q              (tx_clk_oddr            )
    );
OBUFDS i_tx_clk_obuf (
    .I              (tx_clk_oddr),
    .O              (tx_clk_out_p),
    .OB             (tx_clk_out_n)
);
    
endmodule
