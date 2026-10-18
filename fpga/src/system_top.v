module system_top(
//系统输入时钟
    input               i_clk,
//AD936X SPI配置
    output              o_spi_clk,
    output              o_spi_csn,
    input               i_spi_miso,
    output              o_spi_mosi,
//AD936X 状态控制引脚
    output              en_agc,
    output reg          enable,
    output reg          txnrx,
    output              chip_rst_n,
    output              sync_in,
    output      [3:0]   ctrl_in,
//AD936X 接收通道数据引脚
    input               rx_clk_in_p,
    input               rx_clk_in_n,
    input       [5:0]   rx_data_in_n,
    input       [5:0]   rx_data_in_p,
    input               rx_frame_in_n,
    input               rx_frame_in_p,
//AD936X 发射通道数据引脚
    output              tx_clk_out_n,
    output              tx_clk_out_p,
    output      [5:0]   tx_data_out_n,
    output      [5:0]   tx_data_out_p,
    output              tx_frame_out_n,
    output              tx_frame_out_p
);

/*****全局时钟与复位*****/
wire                    clk_100M    ;
wire                    pll_locked  ;
wire                    sys_rst     ;
// 原工程用 Xilinx clk_wiz IP（50 MHz -> 100 MHz）。该 IP 的 .xci 是 Vivado 2021.1
// 产物，而本板必须用 2018.3 构建（唯一装了 xc7z010clg400-1 的版本），因此改用
// 纯原语实现（MMCME2_BASE + BUFG），参数与原 IP 完全一致（*20 / /10）。
clk_pll clk_pll_u
(
    .clk_in1            (i_clk      ),
    .clk_out1           (clk_100M   ),  //100mhz
    .locked             (pll_locked )
);

assign  sys_rst = ~ pll_locked      ;

/*****产生分频时钟与复位*****/
wire                    spi_clk     ;
wire                    spi_rst     ;

CLK_DIV_module#(
    .P_CLK_DIV_CNT     (4           )     
)
CLK_DIV_module_U0
(
    .i_clk              (clk_100M   ),  
    .i_rst              (sys_rst    ),  
    .o_clk_div          (spi_clk    )   
);

rst_gen_module#
(
    .P_RST_CYCLE        (10         )   
)
rst_gen_module_U0
(
    .i_clk              (spi_clk    ),
    .o_rst              (spi_rst    )    
);

/*****AD936X 初始化*****/

//赋值936X接口
assign en_agc = 'd0;        
assign sync_in = 1'b1;
assign ctrl_in = 4'b0000;
wire   ad9361_config_init_done;    //初始化完成信号，高电平完成

AD936X_Init AD936X_Init_U0(
    .i_clk              (spi_clk                ),
    .i_rst              (spi_rst                ),
    .chip_rst_n         (chip_rst_n             ),
    .init_done          (ad9361_config_init_done),
    .o_spi_clk          (o_spi_clk              ),
    .o_spi_cs           (o_spi_csn              ),
    .o_spi_mosi         (o_spi_mosi             ),
    .i_spi_miso         (i_spi_miso             )
);
always @ (posedge spi_clk or posedge spi_rst)begin
    if (spi_rst) begin
        enable <= 1'b0;
        txnrx <= 1'b0;  
    end
    else begin  
        if (ad9361_config_init_done == 1'b1) begin
                enable <= 1'b0;
                txnrx <= 1'b1; 
        end  
    end
end

/*****AD936X驱动接口*****/

//采样时钟
wire             sample_clk;  
//信号接口
wire [11:0]      rx0_i_data;
wire [11:0]      rx0_q_data;
wire [11:0]      rx1_i_data;
wire [11:0]      rx1_q_data;
wire  [11:0]     tx0_i_data;
wire  [11:0]     tx0_q_data;
wire  [11:0]     tx1_i_data;
wire  [11:0]     tx1_q_data;

//=============================================================================
// 数据源：CCSDS 发射链 取代原来的 4 个 DDS
//
// 原设计用 4 个 DDS 分别驱动 tx0_i / tx0_q / tx1_i / tx1_q（各 12 位，@ sample_clk）。
// 现在由 ccsds_tx_lvds 产生 CCSDS 131.0-B 的 BPSK I/Q 样点：
//     tx0_i / tx0_q  <- CCSDS（BPSK 只占一路，另一路恒 0）
//     tx1_i / tx1_q  <- 0（本设计只用通道 0）
// LVDS 串化仍由 data_process 完成，本模块只给并行样点，因此这里没有 ODDR。
//
// 注意：原来的 vendor DDS 把 "i" 实例接到 tx0_q_data、"q" 实例接到 tx0_i_data
// （I/Q 交叉）。对正交单音看不出差别，但对只占一路的 BPSK 有影响，所以
// ccsds_tx_lvds 里留了 SWAP_IQ 参数可以两种接法都试。
//=============================================================================
wire ccsds_buf_ful;
wire ccsds_idle;
wire ccsds_running;
wire [7:0] ccsds_sam_i_tap;      // ★ 发射端 8 位成形样点，引出来给接收机做数字环回
wire       ccsds_sym_tap;        // ★ 板级定位：mapper 出来的符号位（滤波链之前）
wire [7:0] ccsds_flt_a_tap;      // ★ 板级定位：符号->幅度量化后（未上采样）
wire [7:0] ccsds_flt_b_tap;      // ★ 板级定位：oversampler 输出（SRRC 输入）

ccsds_tx_lvds #(
    .DATA_BUS_SIZE   (16),
    .OVERSAMPLING    (10),
    .SIG_QUANT_DEPTH (8),
    .DAC_WIDTH       (12),
    .SCALE_SHIFT     (5),
    .INVERT_BPSK     (1),
    .SWAP_IQ         (0)
) ccsds_tx_lvds_U0 (
    .clk      (sample_clk),
    .enable   (ad9361_config_init_done),
    .tx_i     (tx0_i_data),
    .tx_q     (tx0_q_data),
    .buf_ful  (ccsds_buf_ful),
    .idle     (ccsds_idle),
    .running  (ccsds_running),
    .sam_i_o  (ccsds_sam_i_tap),
    .tx_sym_o (ccsds_sym_tap),
    .flt_a_o  (ccsds_flt_a_tap),
    .flt_b_o  (ccsds_flt_b_tap)
);

assign tx1_i_data = 12'd0;
assign tx1_q_data = 12'd0;

//=============================================================================
// ★ 板内数字环回验证：TX 的成形样点直接接进 RX，判据是"发送内容 == 接收内容"
//
// 为什么用数字环回而不是射频环回：
//   厂商初始化把 TX 本振设成 2500 MHz、RX 本振设成 2400 MHz，相差 100 MHz，
//   远超 9 MHz 接收带宽，板内 TX->RX 电缆直连根本收不到。改本振要动
//   AD936X_lut.v 的寄存器表，风险大且与"转发板做 CCSDS 接收"的最终架构无关。
//   数字环回验证的是【CCSDS 编码 + 调制 + 解调 + 译码 + 组帧】这整条算法链，
//   这正是本次移植要证明的东西；射频链路由 AD9361 本身保证（已在别处验证）。
//
// 时序参数来自仿真定标（sim/run_rx_ideal.ps1 + sim/run_loopback.ps1）：
//   PHASE     = 9   （10 个抽取相位中，0/4/5/6/7/8/9 都能通过）
//   INVERT_IN = 1   （euryspace 的 SRRC 反相，与 TX 的 INVERT_BPSK=1 成对）
//=============================================================================
wire        rx_sym_val, rx_bit_out, rx_asm_hit, rx_byte_val, rx_frame_valid, rx_crc_ok;
wire [15:0] rx_err_cnt, rx_data_bit_cnt, rx_crc_calc, rx_crc_rx;
wire [ 7:0] rx_frame_byte, rx_frame_idx, rx_lfsr_dbg;
wire [ 1:0] rx_state_dbg;
wire signed [7:0] ccsds_rx_mf_tap;   // ★ 接收机匹配滤波输出（板级定位）

ccsds_rx_lvds #(
    .OVERSAMPLING (10),
    .SAMP_W       (8),
    .PHASE        (9),
    .INVERT_IN    (1),
    .FRAME_BYTES  (40),
    .ASM          (32'h1ACFFC1D)
) ccsds_rx_lvds_U0 (
    .clk           (sample_clk),
    .rst           (~ad9361_config_init_done),
    .ena           (ad9361_config_init_done),
    .sam_i         (ccsds_sam_i_tap),
    .sam_q         (8'sd0),
    .sym_val       (rx_sym_val),
    .bit_out       (rx_bit_out),
    .asm_hit       (rx_asm_hit),
    .err_cnt       (rx_err_cnt),
    .data_bit_cnt  (rx_data_bit_cnt),
    .byte_val      (rx_byte_val),
    .frame_byte    (rx_frame_byte),
    .frame_idx     (rx_frame_idx),
    .frame_valid   (rx_frame_valid),
    .crc_calc      (rx_crc_calc),
    .crc_rx        (rx_crc_rx),
    .crc_ok        (rx_crc_ok),
    .lfsr_dbg      (rx_lfsr_dbg),
    .state_dbg     (rx_state_dbg),
    .mf_dbg_o      (ccsds_rx_mf_tap)
);

//--------------------------------------------------------------------------
// 发送内容 vs 接收内容 的硬件比对
//
// 期望帧与 Src/ccsds/ccsds_tx_datalink_layer.vhd 里的 STATIC_FRAME 完全一致
// （40 字节）。每解出一个字节就与期望的同序号字节比，累计不匹配数；
// 一帧结束时把结果锁存到 frame_match（★ 粘滞，方便用 100 MHz 的 ILA 抓）。
//
// 注意 rx_frame_idx 的时序：RX 内部 frame_byte 与 frame_idx 的 +1 是同拍发生的，
// 所以 byte_val 有效那一拍，frame_idx 已经是【下一个】字节的序号，要用 idx-1。
//--------------------------------------------------------------------------
localparam [319:0] EXPECTED_FRAME =
    320'h02a00000180043435344532d36472d4e544e2d373031302d5454432d465047412d504f5254210463;

wire [7:0] exp_byte = EXPECTED_FRAME[ 319 - 8*(rx_frame_idx - 8'd1) -: 8 ];

reg [7:0] rx_mismatch_cnt = 8'd0;
reg       frame_match     = 1'b0;
reg [15:0] match_cnt      = 16'd0;   // 匹配成功的帧数（只增不减，作永久证据）

always @(posedge sample_clk) begin
    if (rx_asm_hit) begin
        rx_mismatch_cnt <= 8'd0;            // 新一帧开始，清零
    end else if (rx_byte_val) begin
        if (rx_frame_byte != exp_byte)
            rx_mismatch_cnt <= rx_mismatch_cnt + 8'd1;
    end

    if (rx_frame_valid && (rx_mismatch_cnt == 8'd0)) begin
        // ★ 真正粘滞：一旦有过一帧逐字节全对，就永远保持 1，不再被后续帧冲掉。
        //   第一版写成 frame_match <= (rx_mismatch_cnt == 0) 每次都覆盖，
        //   结果它在 1/0 之间跳变 —— ILA 触发能抓到 1，但事后抓取窗口略偏就只看得到 0，
        //   非常容易误判成"没通过"。踩过这个坑，记在这里。
        frame_match <= 1'b1;
        match_cnt   <= match_cnt + 16'd1;
    end
end

//=============================================================================
// 调试用 ILA（只在诊断构建里加入；发布位流里可去掉）
//
// 两个关键设计决定：
//
// 1) ILA 用 clk_100M（MMCM 输出的常驻时钟）采样，不用 sample_clk。
//    第一版 ILA 用 sample_clk 采样，结果 Vivado 报
//        [Labtools 27-1434] ... no supported debug core(s) in it
//    因为没有时钟驱动调试核，JTAG 就访问不到它。用常驻时钟后调试核一定可访问。
//
// 2) 加一个 sample_clk 边沿计数器 sample_clk_cnt（在 clk_100M 域里数）。
//      计数在涨  -> AD9361 已被 PL 的 SPI 初始化成功，正在输出 DATA_CLK
//      计数不动  -> 初始化失败（SPI 没通 / 复位没放 / i_clk 缺失）
//
// ★ 本轮改版：探针全部改成"数字环回验证"用的信号。
//
// 判据（按重要性排序）：
//   probe0 frame_match          ★★★ 发送内容 == 接收内容（粘滞，全对后保持 1）
//   probe1 rx_crc_ok            接收端 CRC 校验通过
//   probe2 rx_err_cnt           译码器检出的非法输出对数（0 = 无误码）
//   probe3 rx_mismatch_cnt      逐字节不匹配数（0 = 40 字节完全一致）
//   probe4 rx_asm_hit           ASM 同步命中（脉冲，可与 probe0 对照）
//   probe5 rx_frame_valid       一帧解出（脉冲）
//   probe6 {rx_frame_idx,rx_frame_byte}   解出的字节序列（可逐个核对）
//   probe7 ccsds_sam_i_tap      发射端 8 位成形样点（看波形是否正常）
//   probe8 sample_clk_cnt       ★ DATA_CLK 活动计数器（AD9361 活了没有）
//   probe9 {init_done,enable,txnrx,chip_rst_n}
//
// 抓取方法见 program_and_capture.tcl；判据是 probe0 抓到 1。
//=============================================================================
reg [15:0] sample_clk_cnt = 16'd0;
reg        sample_clk_d   = 1'b0;

always @(posedge clk_100M) begin
    sample_clk_d <= sample_clk;
    if (sample_clk & ~sample_clk_d)
        sample_clk_cnt <= sample_clk_cnt + 1'b1;
end

ila_0 ila_U0 (
    .clk     (clk_100M),
    .probe0  (frame_match),                                  // 1   ★ 粘滞判据
    .probe1  (rx_crc_ok),                                    // 1
    .probe2  (rx_err_cnt),                                   // 16  译码器非法输出对（0=无误码）
    .probe3  (match_cnt[7:0]),                               // 8   ★ 匹配成功帧数
    .probe4  (ccsds_sam_i_tap),                              // 8   SRRC 输出（最终）
    .probe5  (ccsds_flt_a_tap),                              // 8   ★ 符号->幅度量化后（未上采样）
    .probe6  (ccsds_flt_b_tap),   // ★ 改回: SRRC 的输入（看零插值间隔是否规律）                              // 8   ★ 接收机匹配滤波输出
    .probe7  (ccsds_rx_mf_tap),   // ★ 换成接收机匹配滤波输出                        // 8   ★ mapper 符号位
    .probe8  (sample_clk_cnt),                               // 16
    .probe9  ({rx_frame_idx, rx_frame_byte}),                // 16
    .probe10 ({rx_state_dbg, rx_asm_hit, rx_frame_valid}),  // 4  ★ 接收机状态机 + 命中/成帧
    .probe11 ({enable, txnrx, chip_rst_n})                   // 3
);

data_process data_process_U0(
//接收数据通道
    .rx_clk_in_p                (rx_clk_in_p   ),
    .rx_clk_in_n                (rx_clk_in_n   ),
    .rx_frame_in_p              (rx_frame_in_p ),   
    .rx_frame_in_n              (rx_frame_in_n ),
    .rx_data_in_p               (rx_data_in_p  ),
    .rx_data_in_n               (rx_data_in_n  ),
//发送数据通道
    .tx_clk_out_p               (tx_clk_out_p  ),
    .tx_clk_out_n               (tx_clk_out_n  ),
    .tx_frame_out_p             (tx_frame_out_p),
    .tx_frame_out_n             (tx_frame_out_n),
    .tx_data_out_p              (tx_data_out_p ),
    .tx_data_out_n              (tx_data_out_n ),
//复位信号
    .reset                      (~ad9361_config_init_done),
    .sample_clk                 (sample_clk),
//接收数据信号
    .rx0_i_data                 (rx0_i_data ),
    .rx0_q_data                 (rx0_q_data ),
    .rx1_i_data                 (rx1_i_data ),
    .rx1_q_data                 (rx1_q_data ),
     
    .tx0_i_data                 (tx0_i_data),
    .tx0_q_data                 (tx0_q_data),
    .tx1_i_data                 (tx1_i_data),
    .tx1_q_data                 (tx1_q_data)
    );

endmodule
