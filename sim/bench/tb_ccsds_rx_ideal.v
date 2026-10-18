//=============================================================================
// tb_ccsds_rx_ideal.v -- 用【理想激励】单独验证 CCSDS 接收机
//
//   激励来自 sim/out/rx_stim_i.mem，由 gen_rx_stimulus.py 用已验证的 Python
//   参考模型（ccsds_tm_tx.py）生成：静态帧 -> build_cadu -> BPSK -> 上采样x10
//   -> 61 抽头 SRRC -> 量化到 8 位。参数与 FPGA 完全对齐（β=0.35、61 抽头、
//   过采样 10、bit0→+）。
//
// 为什么必须用理想激励，而不是 FPGA 自己发射链的输出：
//   发射链现在有一个未查清的 16 位字边界问题（672 位里错 42 位）。
//   若拿它当激励，解不出来时分不清是发射链错还是接收机错。
//   用理想激励可以把接收机【单独】判死。
//
// 判据：ASM 命中 + err_cnt==0 + CRC 通过 + 40 字节逐字节一致
//
// 运行（PHASE 可扫，找最佳采样相位）：
//   vsim -c -gPHASE=3 -do "run -all; quit -f" work.tb_ccsds_rx_ideal
//=============================================================================

`timescale 1ns/100ps

module tb_ccsds_rx_ideal;

  parameter integer PHASE   = 3;
  parameter integer NSAMP   = 7180;      // 与 gen_rx_stimulus.py 的 samples 一致
  parameter integer FRMBYT  = 40;

  reg clk = 1'b0;
  always #5 clk = ~clk;                  // 100 MHz

  reg rst = 1'b1;
  reg ena = 1'b0;

  //--------------------------------------------------------------------------
  // 激励存储
  //--------------------------------------------------------------------------
  reg signed [7:0] stim [0:NSAMP-1];
  integer          i;
  integer          rd;
  integer          n_read = 0;
  reg [8*260:1]    memfile;

  initial begin
    memfile = "E:/ccsds_fpga/sim/out/rx_stim_i.mem";
    rd = $fopen(memfile, "r");
    if (rd == 0) begin
      $display("!!! 打不开激励文件 %0s", memfile);
      $display("!!! 先运行 python E:\\ccsds_fpga\\sim\\gen_rx_stimulus.py");
      $finish;
    end
    for (i = 0; i < NSAMP; i = i + 1) begin
      if ($fscanf(rd, "%d\n", stim[i]) == 1) n_read = n_read + 1;
    end
    $fclose(rd);
    $display("");
    $display("激励文件读入 %0d / %0d 个样点", n_read, NSAMP);
  end

  //--------------------------------------------------------------------------
  // DUT：就是板上/转发板上要用的同一份接收机
  //--------------------------------------------------------------------------
  reg  signed [7:0] sam;
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
    .sam_i         (sam),
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
  // 期望帧（与 gen_rx_stimulus.py 的 EXPECTED 一致，40 字节）
  //--------------------------------------------------------------------------
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

  //--------------------------------------------------------------------------
  // 诊断转储：输入样点、匹配滤波输出、硬判位
  // （第一版连 ASM 都找不到，必须看清中间信号，而不是猜）
  //--------------------------------------------------------------------------
  integer fd_in, fd_mf, fd_bit;
  initial begin
    fd_in  = $fopen("E:/ccsds_fpga/sim/out/rxid_in.txt",  "w");
    fd_mf  = $fopen("E:/ccsds_fpga/sim/out/rxid_mf.txt",  "w");
    fd_bit = $fopen("E:/ccsds_fpga/sim/out/rxid_bit.txt", "w");
  end
  always @(posedge clk) if (ena) begin
    $fwrite(fd_in, "%0d\n", $signed(sam));
    $fwrite(fd_mf, "%0d\n", $signed(u_rx.mf_out));
  end
  always @(posedge clk) if (r_sym_val) $fwrite(fd_bit, "%b\n", r_bit_out);

  reg [7:0] got [0:39];
  integer   nbytes = 0, nframe = 0, mism = 0, k;
  integer   n_asm = 0;

  always @(posedge clk) begin
    // ★ off-by-one：RX 内部 frame_byte 与 frame_idx 的 +1 是同拍发生的，
    //   所以 byte_val 可见那一拍，frame_idx 已经是【下一个】字节的序号。
    //   第一版直接用 r_frame_idx 存，结果 got[k+1]=BYTE_k，明明 CRC 通过却报字节比对失败。
    if (r_byte_val && r_frame_idx >= 1 && r_frame_idx <= 40)
      got[r_frame_idx - 1] <= r_frame_byte;
    if (r_byte_val) nbytes <= nbytes + 1;
    if (r_asm_hit)  n_asm  <= n_asm + 1;
  end

  //--------------------------------------------------------------------------
  // 帧结束判定
  //
  // ★ 时序注意：frame_valid 在第 T 拍被赋值、T+1 可见；而 DUT 里的
  //   crc_calc/crc_rx/crc_ok 是在 T+1 拍赋值、T+2 才可见。
  //   第一版直接在 frame_valid 那一拍就打印，读到的是复位默认值 0，
  //   误判成"CRC 没跑"。所以这里延后 4 拍再打印。
  //--------------------------------------------------------------------------
  reg [3:0] rep_dly = 4'd0;
  always @(posedge clk) begin
    if (r_frame_valid) rep_dly <= 4'd4;
    else if (rep_dly != 4'd0) rep_dly <= rep_dly - 4'd1;
  end

  always @(posedge clk) begin
    if (rep_dly == 4'd1) begin
      nframe <= nframe + 1;
      $display("");
      $display("=============== 解出一帧 (PHASE=%0d) ===============", PHASE);
      $display("  ASM 命中次数   = %0d", n_asm);
      $display("  err_cnt        = %0d   (非法输出对, 0 = 无误码)", r_err_cnt);
      $display("  crc_ok         = %b", r_crc_ok);
      $display("  crc_calc       = %04X   crc_rx = %04X", r_crc_calc, r_crc_rx);
      $write ("  解出帧  : ");
      for (k = 0; k < 40; k = k + 1) $write("%02x", got[k]);
      $write ("\n");
      $write ("  期望帧  : ");
      for (k = 0; k < 40; k = k + 1) $write("%02x", expected[k]);
      $write ("\n");
      mism = 0;
      for (k = 0; k < 40; k = k + 1) if (got[k] !== expected[k]) mism = mism + 1;
      $display("  字节不一致     = %0d", mism);
      if (mism == 0 && r_crc_ok && r_err_cnt == 0)
        $display("  RESULT: *** PASS *** ASM + 无误码 + CRC + 40 字节全对");
      else
        $display("  RESULT: *** FAIL ***");
      $display("===================================================");
    end
  end

  //--------------------------------------------------------------------------
  // 激励时序：复位后把样点逐个送进 DUT
  //--------------------------------------------------------------------------
  integer s;
  initial begin
    $display("");
    $display("tb_ccsds_rx_ideal: PHASE=%0d, %0d 样点", PHASE, NSAMP);
    sam = 8'sd0;
    #200 rst = 1'b0; ena = 1'b1;
    #100;
    for (s = 0; s < NSAMP; s = s + 1) begin
      sam = stim[s];
      @(posedge clk);
    end
    sam = 8'sd0;
    // 留时间收完最后一帧
    repeat (4000) @(posedge clk);
    $display("");
    $display("=== 结束: ASM命中 %0d 次, 完整帧 %0d 个, 累计字节 %0d ===", n_asm, nframe, nbytes);
    if (nframe == 0) $display("!!! 没有解出任何帧 —— 检查 PHASE / 极性 / 帧长");
    $finish;
  end

endmodule
