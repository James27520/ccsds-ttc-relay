//=============================================================================
// ccsds_rx_lvds.v -- CCSDS 131.0-B receiver for the 7010 telemetry board.
//
//   发射 (ccsds_tx_lvds.v):
//       TM 帧 -> CRC-16 -> 伪随机化 -> 卷积编码(7,1/2) -> 插 ASM 0x1ACFFC1D
//             -> BPSK 映射 -> 上采样 x10 -> SRRC 成形 -> sam_i (8 位)
//   接收 (本模块) 是它的严格逆过程：
//       符号抽取 -> 硬判 -> ASM 搜索 -> 查表译码 -> 解随机化 -> CRC 校验 -> 帧输出
//
// 为什么不用 Viterbi
// ------------------
//   本设计目标是无噪数字环回（TX/RX 同一 FPGA、同一时钟）。这种信道上
//   "6 位历史 + 收到的 2 bit"能唯一确定输入位 —— 已用 Python 对全部 64 个状态
//   枚举验证（0 个歧义），并与参考 Viterbi 输出逐位完全相同（640 位 0 差异）。
//   查表译码：
//       给定 dec_hist[5:0]，两条候选路径的输出对是确定的：
//           reg0={hist,1'b0} -> (p1_0,p2_0)     reg1={hist,1'b1} -> (p1_1,p2_1)
//       收到的 (p1,p2) 命中哪条，输入位就是哪个；都不命中 -> err_cnt++
//   代价十几根线，且"非法输出对"计数本身是硬件级误码检测器。
//   将来做射频（有噪）时把这一段换成 Viterbi，接口不变。
//
// 采样相位 PHASE
// --------------
//   已用 Python 量化：无匹配滤波时 [0,1,2,3] 四个相位都能正确解出。
//   仿真里定下 PHASE，板上用【同一个值】—— 这就是"仿真与板上一致"。
//
// 位序/极性/时序（逐项对照 ccsds_tm_tx.py，这几处最容易错）
// --------------------------------------------------------
//   * ASM 0x1ACFFC1D 先发 bit31；移位寄存器装满 32 位后直接比较。
//   * BPSK: bit0->正, bit1->负  =>  硬判 bit = 样点符号位。
//   * 随机化 LFSR: 掩码 0x95、初值 0xFF、输出 bit7、左移、反馈进 bit0、周期 255。
//     ASM 结束处复位（ASM 不参与随机化）。
//   * 卷积码: G1=0b1111001, G2=0b1011011, 第二路取反, 每帧复位 0。
//   * CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, MSB first。
//     帧 = [0..N-3] 数据 + [N-2,N-1] FECF；本地对前 N-2 字节算 CRC 再与帧尾比较。
//
// 修正记录（第一版写错的四个地方，避免以后再犯）
// ----------------------------------------------------------------
//   1) wire 不能声明在 always 内部 -> 全部提到模块层。
//   2) 位式 CRC 必须把【输入位】异或进最高位参与判断：
//        crc_xor = crc_reg[15] ^ crc_bit_in;  crc_next = (crc_reg<<1) ^ (crc_xor?0x1021:0)
//      只写 "最高位为 1 就异或" 是错的（那是没有输入位的版本）。
//   3) 译码必须用【本拍刚解出的位】参与解随机化和组字节，不能用上一拍的 dec_bit。
//      所以 dec_bit 做成组合信号 new_dec_bit，寄存器只做历史更新。
//   4) FECF 比较不能在帧尾同一拍做（fecf_hi/lo 也在那一拍更新，会读到旧值）。
//      改成进 ST_DONE 后下一拍再比较。
//=============================================================================

`timescale 1ns/100ps

module ccsds_rx_lvds #(
  parameter integer OVERSAMPLING = 10,
  parameter integer SAMP_W       = 12,
  parameter integer PHASE        = 5,        // 抽取相位 0..OVERSAMPLING-1（已由理想激励定标为 5）
  parameter integer INVERT_IN    = 1,        // ★ 硬判取反（见下）
  parameter integer FRAME_BYTES  = 40,
  parameter [31:0]  ASM          = 32'h1ACFFC1D
)(
  input  wire                     clk,
  input  wire                     rst,
  input  wire                     ena,
  input  wire signed [SAMP_W-1:0] sam_i,
  input  wire signed [SAMP_W-1:0] sam_q,

  // ---- 调试/状态输出（接 ILA）----
  output reg         sym_val,
  output reg         bit_out,
  output reg         asm_hit,
  output reg  [15:0] err_cnt,
  output reg  [15:0] data_bit_cnt,
  output reg         byte_val,
  output reg  [7:0]  frame_byte,
  output reg  [7:0]  frame_idx,
  output reg         frame_valid,
  output reg  [15:0] crc_calc,
  output reg  [15:0] crc_rx,
  output reg         crc_ok,
  output reg  [7:0]  lfsr_dbg,
  output reg  [1:0]  state_dbg,
  // ★ 板级定位：把匹配滤波输出引出来给 ILA（判断接收机到底收到了什么）
  output wire signed [7:0] mf_dbg_o
);

  localparam integer DATA_BITS = FRAME_BYTES * 8;
  localparam integer CRC_BYTES = FRAME_BYTES - 2;

  localparam [1:0] ST_ASM  = 2'd0;
  localparam [1:0] ST_DATA = 2'd1;
  localparam [1:0] ST_DONE = 2'd2;

  reg [1:0] state;
  reg [4:0] ph_cnt;

  //--------------------------------------------------------------------------
  // 1. 符号抽取（每 OVERSAMPLING 个样点抽一个）
  //
  //   ★★★ 自动搜相位（板上必需）★★★
  //   原来固定用 PHASE 一个相位。仿真里 PHASE=9 能过，但板上接收机始终停在
  //   ST_ASM（rx_asm_hit=0、rx_state_dbg=0）—— 说明收发两边抽取相位的相对关系
  //   在硬件上与仿真不一致（两边都从 sample_clk 分频，但分频器的初始相位不同）。
  //
  //   改成：10 个相位各跑一路 ASM 搜索，哪一路先凑满同步字就锁定它，
  //   后续所有抽取都按锁定相位走。这样完全不依赖手工标定的相位常数。
  //
  //   额外的代价很小：ASM 搜索只是 10 个 32 位移位寄存器 + 比较，
  //   匹配滤波器（最贵的那块）仍然是共用的一个。
  //--------------------------------------------------------------------------
  reg  [3:0] locked_phase  = 4'd0;
  reg        phase_locked  = 1'b0;
  wire       sym_stb       = ena && phase_locked && (ph_cnt == {1'b0, locked_phase});

  always @(posedge clk) begin
    if (rst || !ena) ph_cnt <= 5'd0;
    else             ph_cnt <= (ph_cnt == OVERSAMPLING-1) ? 5'd0 : (ph_cnt + 5'd1);
  end

  //--------------------------------------------------------------------------
  // 1.5 匹配滤波（★ 必须）
  //
  //   仿真实测（第一版没加匹配滤波）：解出的位流里 CADU 结构是对的（ASM 每 672
  //   位出现一次），但 96 位里有 7 位错，连 ASM 自身都错 2 位 —— 因为发射端的
  //   SRRC 成形脉冲在符号点上并不为零，直接抽样必然带 ISI。
  //
  //   这里实例化【与发射端完全相同的那个 VHDL 实体】ccsds_rxtx_srrc（默认
  //   window=0 / rolloff=0.35，见该文件头部 PROJECT PATCH 注释）。SRRC×SRRC =
  //   升余弦，符号点上无 ISI。用同一个实体也就保证了仿真与板上一致。
  //
  //   代价：约 1832 LUT（use_dsp="no"，不能改成 yes —— 整设计 DSP 会超 80，
  //   place_design 会以 [Place 30-640] 失败，这是上一轮实测的结论）。
  //--------------------------------------------------------------------------
  wire signed [7:0] mf_in = sam_i[SAMP_W-1 -: 8];   // 取高 8 位（环回是 8 位，射频是 12 位取高位）
  wire        [7:0] mf_out;
  wire              mf_val;

  ccsds_rxtx_srrc #(
    .CCSDS_RXTX_SRRC_OVERSAMPLING_RATIO (OVERSAMPLING),
    .CCSDS_RXTX_SRRC_SIG_QUANT_DEPTH    (8)
  ) u_matched_filter (
    .clk_i     (clk),
    .rst_i     (rst),
    .sam_i     (mf_in),
    .sam_val_i (ena),
    .sam_o     (mf_out),
    .sam_val_o (mf_val)
  );

  //--------------------------------------------------------------------------
  // 2. 硬判（BPSK：负 -> bit1）
  //
  //   ★ 极性：由【理想激励】实验定标（sim\gen_rx_stimulus.py + tb_ccsds_rx_ideal.v）
  //   激励用已验证的参考模型生成（cadu_to_iq 约定：bit0 -> +1），
  //   结果在 PHASE=5、硬判取反时得到 672/672 位全对、零差异。
  //   说明 euryspace 的 SRRC（ccsds_rxtx_srrc.vhd）会反相，所以这里要取反。
  //
  //   与之配套：发射端 ccsds_tx_lvds 的 INVERT_BPSK 必须为 0
  //   （mapper 把 bit0 映射成 -full，再经同一个反相 SRRC，输出才是 bit0 -> +full，
  //    与地面参考一致）。两边是同一个 SRRC，所以这两个设置必须成对。
  //--------------------------------------------------------------------------
  wire hard_bit = mf_out[7] ^ INVERT_IN[0];

  // PROJECT PATCH (板级定位): 把匹配滤波输出引出来给 ILA
  assign mf_dbg_o = mf_out;

  //--------------------------------------------------------------------------
  // 3. 查表译码（组合）
  //--------------------------------------------------------------------------
  reg  [5:0] dec_hist;
  wire [6:0] cand0 = {dec_hist, 1'b0};
  wire [6:0] cand1 = {dec_hist, 1'b1};
  wire p1_0 = ^(cand0 & 7'b1111001);
  wire p2_0 = (^(cand0 & 7'b1011011)) ^ 1'b1;
  wire p1_1 = ^(cand1 & 7'b1111001);
  wire p2_1 = (^(cand1 & 7'b1011011)) ^ 1'b1;

  reg  rx_p1;
  wire match0 = (hard_bit == p2_0) && (rx_p1 == p1_0);
  wire match1 = (hard_bit == p2_1) && (rx_p1 == p1_1);
  wire new_dec_bit = match1;                       // 命中路径 1 则为 1
  wire dec_err     = !match0 && !match1;

  //--------------------------------------------------------------------------
  // 4. ASM 搜索（★ 10 个相位并行，见第 1 节说明）
  //--------------------------------------------------------------------------
  reg  [31:0] asm_sr [0:OVERSAMPLING-1];
  integer     ak;

  always @(posedge clk) begin
    if (rst || !ena) begin
      for (ak = 0; ak < OVERSAMPLING; ak = ak + 1) asm_sr[ak] <= 32'd0;
    end else begin
      for (ak = 0; ak < OVERSAMPLING; ak = ak + 1)
        if (ph_cnt == ak[4:0]) asm_sr[ak] <= {asm_sr[ak][30:0], hard_bit};
    end
  end

  // 组合判断：这一拍哪一路刚好凑满 32 位同步字（ph_cnt 单热，最多命中一路）
  reg        asm_found;
  reg  [3:0] asm_found_ph;
  integer    aj;

  always @* begin
    asm_found    = 1'b0;
    asm_found_ph = 4'd0;
    for (aj = 0; aj < OVERSAMPLING; aj = aj + 1)
      if ((ph_cnt == aj[4:0]) && ({asm_sr[aj][30:0], hard_bit} == ASM)) begin
        asm_found    = 1'b1;
        asm_found_ph = aj[3:0];
      end
  end

  //--------------------------------------------------------------------------
  // 5. 解随机化 LFSR
  //--------------------------------------------------------------------------
  reg  [7:0] lfsr;
  wire lfsr_fb  = lfsr[0] ^ lfsr[2] ^ lfsr[4] ^ lfsr[7];

  // ★ 用本拍刚解出的位参与解随机化（不是上一拍的 dec_bit）
  wire data_bit = new_dec_bit ^ lfsr[7];

  //--------------------------------------------------------------------------
  // 6. 位式 CRC-16/CCITT-FALSE（MSB first），后台每字节 8 拍
  //--------------------------------------------------------------------------
  reg  [15:0] crc_reg;
  reg  [7:0]  crc_byte_sr;
  reg  [2:0]  crc_bit_idx;
  reg         crc_busy;

  wire        crc_bit_in = crc_byte_sr[7];
  wire        crc_xor    = crc_reg[15] ^ crc_bit_in;       // ★ 必须异或输入位
  wire [15:0] crc_next   = (crc_reg << 1) ^ (crc_xor ? 16'h1021 : 16'h0000);

  //--------------------------------------------------------------------------
  // 7. 配对 / 组字节 / FECF
  //--------------------------------------------------------------------------
  reg        pair_sel;
  reg  [7:0] byte_shift;
  reg  [2:0] byte_bit_idx;
  reg  [7:0] fecf_hi, fecf_lo;
  reg        done_d;               // ST_DONE 的下一拍，用于安全比较 FECF

  integer i;

  always @(posedge clk) begin
    if (rst || !ena) begin
      state        <= ST_ASM;
      dec_hist     <= 6'd0;
      rx_p1        <= 1'b0;
      // asm_sr 是数组，在它自己的 always 块里复位（见第 4 节）
      phase_locked <= 1'b0;
      locked_phase <= 4'd0;
      lfsr         <= 8'hFF;
      crc_reg      <= 16'hFFFF;
      crc_byte_sr  <= 8'd0;
      crc_bit_idx  <= 3'd0;
      crc_busy     <= 1'b0;
      pair_sel     <= 1'b0;
      byte_shift   <= 8'd0;
      byte_bit_idx <= 3'd0;
      fecf_hi      <= 8'd0;
      fecf_lo      <= 8'd0;
      done_d       <= 1'b0;
      sym_val      <= 1'b0;
      bit_out      <= 1'b0;
      asm_hit      <= 1'b0;
      err_cnt      <= 16'd0;
      data_bit_cnt <= 16'd0;
      byte_val     <= 1'b0;
      frame_byte   <= 8'd0;
      frame_idx    <= 8'd0;
      frame_valid  <= 1'b0;
      crc_calc     <= 16'd0;
      crc_rx       <= 16'd0;
      crc_ok       <= 1'b0;
      lfsr_dbg     <= 8'hFF;
      state_dbg    <= ST_ASM;
    end else begin
      // 默认脉冲拉低
      sym_val     <= 1'b0;
      byte_val    <= 1'b0;
      frame_valid <= 1'b0;
      asm_hit     <= 1'b0;
      done_d      <= (state == ST_DONE) && (state_dbg != ST_DONE) ? 1'b1 : 1'b0;
      lfsr_dbg    <= lfsr;

      // ---- CRC 后台推进 ----
      if (crc_busy) begin
        crc_reg     <= crc_next;
        crc_byte_sr <= {crc_byte_sr[6:0], 1'b0};
        if (crc_bit_idx == 3'd7) begin
          crc_busy    <= 1'b0;
          crc_bit_idx <= 3'd0;
        end else begin
          crc_bit_idx <= crc_bit_idx + 3'd1;
        end
      end

      // ---- ST_DONE 下一拍做 FECF 比较（避开同拍更新竞争）----
      if (state == ST_DONE && state_dbg == ST_DONE && !crc_ok && !done_d) begin
        crc_calc <= crc_reg;
        crc_rx   <= {fecf_hi, fecf_lo};
        crc_ok   <= (crc_reg == {fecf_hi, fecf_lo});
      end

      //----------------------------------------------------------------------
      // ★ ASM 搜索：与 sym_stb 无关！
      //
      //   10 个相位各自的移位寄存器在凑满 32 位的【那一拍】由 asm_found 报出，
      //   此时 ph_cnt 正等于命中的相位。这里立刻锁存该相位并使能抽取。
      //
      //   ★ 关键：不能把这段放进 if (sym_stb) 里 —— sym_stb 需要 phase_locked，
      //     而 phase_locked 要靠这段置起，放进去就是死锁（改的时候踩过）。
      //----------------------------------------------------------------------
      if ((state == ST_ASM) && asm_found) begin
        asm_hit      <= 1'b1;
        locked_phase <= asm_found_ph;
        phase_locked <= 1'b1;
        state        <= ST_DATA;
        state_dbg    <= ST_DATA;
        dec_hist     <= 6'd0;
        lfsr         <= 8'hFF;            // ASM 不参与随机化
        pair_sel     <= 1'b0;
        byte_shift   <= 8'd0;
        byte_bit_idx <= 3'd0;
        data_bit_cnt <= 16'd0;
        frame_idx    <= 8'd0;
        crc_reg      <= 16'hFFFF;
        crc_busy     <= 1'b0;
        crc_ok       <= 1'b0;
      end

      if (sym_stb) begin
        sym_val <= 1'b1;
        bit_out <= hard_bit;

        case (state)
          //----------------------------------------------------------------
          ST_ASM: ;   // 由上面的 asm_found 分支处理（这里不会再有活）

          //----------------------------------------------------------------
          ST_DATA: begin
            if (!pair_sel) begin
              rx_p1    <= hard_bit;
              pair_sel <= 1'b1;
            end else begin
              pair_sel     <= 1'b0;
              dec_hist     <= {dec_hist[4:0], new_dec_bit};
              lfsr         <= {lfsr[6:0], lfsr_fb};
              data_bit_cnt <= data_bit_cnt + 16'd1;
              if (dec_err) err_cnt <= err_cnt + 16'd1;

              // 字节组装（MSB first），用的是本拍的 data_bit
              if (byte_bit_idx == 3'd7) begin
                byte_bit_idx <= 3'd0;
                byte_val     <= 1'b1;
                frame_byte   <= {byte_shift[6:0], data_bit};
                frame_idx    <= frame_idx + 8'd1;
                fecf_hi      <= fecf_lo;
                fecf_lo      <= {byte_shift[6:0], data_bit};
                if (frame_idx < CRC_BYTES) begin
                  crc_byte_sr <= {byte_shift[6:0], data_bit};
                  crc_busy    <= 1'b1;
                  crc_bit_idx <= 3'd0;
                end
              end else begin
                byte_bit_idx <= byte_bit_idx + 3'd1;
              end
              byte_shift <= {byte_shift[6:0], data_bit};

              if (data_bit_cnt == DATA_BITS-1) begin
                state       <= ST_DONE;
                state_dbg   <= ST_DONE;
                frame_valid <= 1'b1;
              end
            end
          end

          ST_DONE: begin
            // 结果保持，ena 拉低即可复位重来
          end
        endcase
      end
    end
  end

endmodule
