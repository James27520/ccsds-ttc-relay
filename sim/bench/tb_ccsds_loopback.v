//=============================================================================
// tb_ccsds_loopback.v -- 数字环回：把发射链的输出直接接进接收链
//
//   ccsds_tx_lvds ──► sam_i_o (8 位 SRRC 成形样点) ──► ccsds_rx_lvds
//
// 这是"仿真与板上一致"的关键环节：
//   * 两个 DUT 就是板上用的同一份 RTL（E:\ccsds_fpga\rtl\adapter\*.v）
//   * 期望值来自发射端自己的静态帧常量 STATIC_FRAME
//     (ccsds_tx_datalink_layer.vhd 第 138 行)，不是我另外手写的
//   * PHASE 由仿真定下来，板上用同一个值
//
// 运行（PHASE 通过 -g 传参，便于扫相位）：
//   vsim -c -gPHASE=0 -do "run -all; quit -f" work.tb_ccsds_loopback
//
// 判据（与软件版报告第四层一致）：ASM 命中 + CRC 通过 + 40 字节逐字节一致
//=============================================================================

`timescale 1ns/100ps

module tb_ccsds_loopback;

  // ---- 时钟：与板上 sample_clk 同频量级即可，逻辑与时序无关 ----
  reg clk = 1'b0;
  always #5 clk = ~clk;              // 100 MHz

  reg rst = 1'b1;
  reg ena = 1'b0;

  // ---- 发射链 ----
  wire [11:0] tx_i, tx_q;
  wire [ 7:0] tx_sam_i;              // ★ 环回点：8 位 SRRC 成形输出
  wire        tx_buf_ful, tx_idle, tx_running;

  ccsds_tx_lvds #(
    .DATA_BUS_SIZE   (16),
    .OVERSAMPLING    (10),
    .SIG_QUANT_DEPTH (8),
    .DAC_WIDTH       (12),
    .SCALE_SHIFT     (3),
    .INVERT_BPSK     (1),
    .SWAP_IQ         (0)
  ) u_tx (
    .clk     (clk),
    .enable  (ena),
    .tx_i    (tx_i),
    .tx_q    (tx_q),
    .sam_i_o (tx_sam_i),
    .buf_ful (tx_buf_ful),
    .idle    (tx_idle),
    .running (tx_running)
  );

  // ---- 接收链（PHASE 可参数化，便于扫相位找最佳值）----
  parameter integer PHASE = 3;

  wire        r_sym_val, r_bit_out, r_asm_hit, r_byte_val, r_frame_valid, r_crc_ok;
  wire [15:0] r_err_cnt, r_data_bit_cnt, r_crc_calc, r_crc_rx;
  wire [ 7:0] r_frame_byte, r_frame_idx, r_lfsr_dbg;
  wire [ 1:0] r_state_dbg;

  ccsds_rx_lvds #(
    .OVERSAMPLING (10),
    .SAMP_W       (8),
    .PHASE        (PHASE),
    .FRAME_BYTES  (40),
    .ASM          (32'h1ACFFC1D)
  ) u_rx (
    .clk           (clk),
    .rst           (rst),
    .ena           (ena),
    .sam_i         (tx_sam_i),
    .sam_q         (8'sd0),
    .sym_val       (r_sym_val),
    .bit_out       (r_bit_out),
    .asm_hit       (r_asm_hit),
    .err_cnt       (r_err_cnt),
    .data_bit_cnt  (r_data_bit_cnt),
    .byte_val      (r_byte_val),
    .frame_byte    (r_frame_byte),
    .frame_idx     (r_frame_idx),
    .frame_valid   (r_frame_valid),
    .crc_calc      (r_crc_calc),
    .crc_rx        (r_crc_rx),
    .crc_ok        (r_crc_ok),
    .lfsr_dbg      (r_lfsr_dbg),
    .state_dbg     (r_state_dbg)
  );

  //--------------------------------------------------------------------------
  // 诊断转储：把环回样点和接收端硬判位写文件，便于在 Python 里搜 ASM
  // （第一版跑出 frames=0，必须先把"位流对不对"查清，而不是猜 PHASE 或极性）
  // 注意：必须放在 RX 实例之后 —— 否则引用 sym_val/bit_out 会报未定义。
  //--------------------------------------------------------------------------
  integer fd_samp, fd_bits, fd_mf;
  initial begin
    fd_samp = $fopen("E:/ccsds_fpga/sim/out/rx_samp.txt", "w");
    fd_bits = $fopen("E:/ccsds_fpga/sim/out/rx_bits.txt", "w");
    fd_mf   = $fopen("E:/ccsds_fpga/sim/out/rx_mf.txt",   "w");
  end
  always @(posedge clk) begin
    if (ena) begin
      $fwrite(fd_samp, "%0d\n", $signed(tx_sam_i));
      // 层次引用取匹配滤波输出（RX 内部信号），用于离线逐相位分析
      $fwrite(fd_mf,   "%0d\n", $signed(u_rx.mf_out));
    end
    if (r_sym_val)     $fwrite(fd_bits, "%b %b %b\n", r_bit_out, r_asm_hit, r_frame_valid);
  end

  //--------------------------------------------------------------------------
  // 收集解出的帧字节，与发射端 STATIC_FRAME 比对
  //--------------------------------------------------------------------------
  // 发射端静态帧（ccsds_tx_datalink_layer.vhd:138），40 字节
  reg [7:0] expected [0:39];
  initial begin
    expected[ 0]=8'h02; expected[ 1]=8'ha0; expected[ 2]=8'h00; expected[ 3]=8'h00;
    expected[ 4]=8'h18; expected[ 5]=8'h00;
    expected[ 6]=8'h43; expected[ 7]=8'h43; expected[ 8]=8'h53; expected[ 9]=8'h44;
    expected[10]=8'h53; expected[11]=8'h2d; expected[12]=8'h36; expected[13]=8'h47;
    expected[14]=8'h2d; expected[15]=8'h4e; expected[16]=8'h54; expected[17]=8'h4e;
    expected[18]=8'h2d; expected[19]=8'h37; expected[20]=8'h30; expected[21]=8'h31;
    expected[22]=8'h30; expected[23]=8'h2d; expected[24]=8'h54; expected[25]=8'h54;
    expected[26]=8'h43; expected[27]=8'h2d; expected[28]=8'h46; expected[29]=8'h50;
    expected[30]=8'h47; expected[31]=8'h41; expected[32]=8'h2d; expected[33]=8'h50;
    expected[34]=8'h4f; expected[35]=8'h52; expected[36]=8'h54; expected[37]=8'h21;
    expected[38]=8'h04; expected[39]=8'h63;
  end

  reg [7:0] got [0:39];
  integer   nbytes = 0;
  integer   nframe = 0;
  integer   i;
  integer   mism;

  // 字节收集
  // ★ off-by-one：RX 内部 frame_byte 与 frame_idx 的 +1 是同拍发生的，
  //   所以 byte_val 可见那一拍，frame_idx 已经是【下一个】字节的序号。
  always @(posedge clk) begin
    if (r_byte_val) begin
      if (r_frame_idx >= 1 && r_frame_idx <= 40) got[r_frame_idx - 1] <= r_frame_byte;
      nbytes <= nbytes + 1;
    end
  end

  // 帧结束判定
  // ★ 时序：frame_valid 在 T 拍赋值、T+1 可见；而 RX 的 crc_calc/crc_rx/crc_ok
  //   在 T+1 拍赋值、T+2 才可见。第一版直接在 frame_valid 那拍打印，读到的是
  //   复位默认值 0，误判成"CRC 没跑"。这里延后 4 拍。
  reg [3:0] rep_dly = 4'd0;
  always @(posedge clk) begin
    if (r_frame_valid) rep_dly <= 4'd4;
    else if (rep_dly != 4'd0) rep_dly <= rep_dly - 4'd1;
  end

  always @(posedge clk) begin
    if (rep_dly == 4'd1) begin
      nframe <= nframe + 1;
      $display("");
      $display("================ FRAME %0d COMPLETE ================", nframe+1);
      $display("  PHASE          = %0d", PHASE);
      $display("  asm_hit count  = (see above)");
      $display("  err_cnt        = %0d  (非法输出对，0 = 无误码)", r_err_cnt);
      $display("  crc_ok         = %b", r_crc_ok);
      $display("  crc_calc       = %04X", r_crc_calc);
      $display("  crc_rx         = %04X", r_crc_rx);
      $display("  decoded frame  :");
      $write("    ");
      for (i = 0; i < 40; i = i + 1) $write("%02x", got[i]);
      $write("\n");
      $display("  expected frame :");
      $write("    ");
      for (i = 0; i < 40; i = i + 1) $write("%02x", expected[i]);
      $write("\n");
      mism = 0;
      for (i = 0; i < 40; i = i + 1) if (got[i] !== expected[i]) mism = mism + 1;
      $display("  byte mismatches= %0d", mism);
      if (mism == 0 && r_crc_ok)
        $display("  RESULT: *** PASS *** ASM + CRC + 40 bytes all match");
      else
        $display("  RESULT: *** FAIL ***");
      $display("====================================================");
    end
  end

  //--------------------------------------------------------------------------
  // 激励：跑足够久以覆盖整帧（40 字节 -> 320 bit -> 640 coded -> 672 CADU bit
  //       每 bit 10 个样点 => 6720 样点；留 3 倍余量）
  //--------------------------------------------------------------------------
  initial begin
    $display("");
    $display("tb_ccsds_loopback start, PHASE=%0d", PHASE);
    #200 rst = 1'b0; ena = 1'b1;
    #400000;                       // 400us @100MHz = 40k 周期 ≈ 4000 符号 ≈ 6 个 CADU（够用且快 15 倍）
    $display("");
    $display("=== simulation timeout: frames=%0d bytes=%0d ===", nframe, nbytes);
    if (nframe == 0) $display("!!! 没有解出任何帧 —— 检查极性 / PHASE / FRAME_BYTES");
    $finish;
  end

endmodule
