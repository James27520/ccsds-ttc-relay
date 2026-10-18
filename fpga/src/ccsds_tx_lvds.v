//=============================================================================
// ccsds_tx_lvds.v -- parallel I/Q output wrapper for the 7010 telemetry board's
//                    AD9361 LVDS data path.
//
// Why this differs from ccsds_tx_wrap.v (the CMOS bring-up wrapper)
// -----------------------------------------------------------------
//   ccsds_tx_wrap.v serialised I and Q onto the 12 CMOS data pins itself with
//   ODDR primitives, because in CMOS 1R1T mode the AD9361 takes I on the rising
//   and Q on the falling edge of DATA_CLK.
//
//   This board does NOT use CMOS. Its AD9361 data interface is LVDS (6
//   differential pairs), confirmed by:
//     * AD936X_only_PL/Src/AD936X.xdc         : LVDS_25 x32, enable=T15, spi_csn=R17
//     * AD936X_PL/.../system_constr.xdc       : identical LVDS pin set
//     * the kernel's cf_axi_adc probe reports version 10.03 on the factory
//       bitstream while the (CMOS, wrong-pin) build reports 10.01.b, and the
//       factory bitstream is the only one that brings the AD9361 up
//     * the board's schematic names the interface DATA_CLK_P/N, TX_FRAME_P/N,
//       P0_D*/TX_D*_P/N
//
//   In LVDS mode the serialisation is done by the vendor's data_process.v, which
//   expects plain parallel 12-bit tx0_i/tx0_q/tx1_i/tx1_q words at sample_clk.
//   So this wrapper deliberately contains NO ODDR: it produces the parallel I/Q
//   pair and lets data_process.v do the SERDES.
//
// Clocking
// --------
//   sample_clk comes out of data_process.v and is the AD9361's DATA_CLK
//   (the design's DDS instances ran on exactly this clock at 56 MHz). ccsds_tx
//   produces one I/Q sample pair per clk_i and its symbol rate is
//   clk_i / OVERSAMPLING, which reproduces the verified software link's rate
//   plan (2.5 MSPS / 250 ksym/s at a 2.5 MHz sample clock, or 5.6 MSPS /
//   560 ksym/s at 56 MHz).
//=============================================================================

`timescale 1ns/100ps

module ccsds_tx_lvds #(
  // ---- CCSDS link configuration (must match the verified software link) ----
  parameter integer DATA_BUS_SIZE    = 16,     // datalink word width
  parameter integer OVERSAMPLING     = 10,     // samples per symbol
  parameter integer SIG_QUANT_DEPTH  = 8,      // core output width
  // ---- DAC interface ----
  parameter integer DAC_WIDTH        = 12,     // AD9363 sample width
  parameter integer SCALE_SHIFT      = 5,      // 8 -> 12 bit gain (2^5 = 32)
  // The euryspace BPSK mapper sends bit 0 -> -full scale and bit 1 -> +full
  // scale, while the verified ground link uses bit 0 -> +1. Without this
  // inversion every bit at the receiver is flipped and the 0x1ACFFC1D ASM can
  // never be found.
  parameter integer INVERT_BPSK      = 1,
  // The vendor's own DDS wiring drove its "i" instance into tx0_q_data and its
  // "q" instance into tx0_i_data, i.e. it swapped I and Q on the way out. That
  // is invisible for a quadrature tone but matters for a BPSK signal carried on
  // one rail only, so keep it switchable and test both.
  parameter integer SWAP_IQ          = 0
)(
  input  wire                     clk,        // = sample_clk, the AD9361 DATA_CLK
  input  wire                     enable,     // 1 = the CCSDS stream drives the DAC
  output wire [DAC_WIDTH-1:0]     tx_i,       // parallel I sample, one per clk
  output wire [DAC_WIDTH-1:0]     tx_q,       // parallel Q sample, one per clk
  // ★ 8 位基带样点（SRRC 成形后、缩放成 12 位之前）引出来给接收机做数字环回。
  //   引出这一路而不是 tx_i，是为了让 RX 看到发射端真实的成形输出，环回才有验证意义。
  output wire [SIG_QUANT_DEPTH-1:0] sam_i_o,  // loopback tap for ccsds_rx_lvds
  output wire                     tx_sym_o,   // ★ 板级定位：mapper 出来的符号位
  output wire [SIG_QUANT_DEPTH-1:0] flt_a_o,  // ★ 板级定位：符号->幅度量化后（未上采样）
  output wire [SIG_QUANT_DEPTH-1:0] flt_b_o,  // ★ 板级定位：oversampler 输出（SRRC 输入）
  output wire                     buf_ful,    // debug: core input buffer full
  output wire                     idle,       // debug: framer inserted idle data
  output wire                     running     // debug: core out of reset and enabled
);

  //--------------------------------------------------------------------------
  // power-on reset
  //--------------------------------------------------------------------------
  reg [7:0] rst_count = 8'h00;
  wire      rst = ~(&rst_count);

  always @(posedge clk)
    if (rst)
      rst_count <= rst_count + 1'b1;

  //--------------------------------------------------------------------------
  // the euryspace CCSDS transmitter (VHDL)
  //
  // ccsds_tx_datalink_layer.vhd runs with
  // CCSDS_TX_DATALINK_STATIC_FRAME_ENABLED = true, so the upstream framer is
  // bypassed and the verified CCSDS 131.0-B randomiser / rate-1/2 convolutional
  // coder / ASM inserter are driven from one fixed CADU built by the ground
  // reference. dat_par_i and dat_val_i therefore have no effect and are tied
  // off. (Swapping in frame_gen.vhd for live telemetry frames is the next step
  // and does not change anything outside the datalink layer.)
  //--------------------------------------------------------------------------
  wire [SIG_QUANT_DEPTH-1:0] sam_i;
  wire [SIG_QUANT_DEPTH-1:0] sam_q;
  wire                       clk_o_unused;
  wire                       ena_o_unused;

  ccsds_tx #(
    .CCSDS_TX_BITS_PER_SYMBOL      (1),                // BPSK
    .CCSDS_TX_BUFFER_SIZE          (16),
    .CCSDS_TX_MODULATION_TYPE      (2),                // 2 = BPSK
    .CCSDS_TX_DATA_BUS_SIZE        (DATA_BUS_SIZE),
    .CCSDS_TX_OVERSAMPLING_RATIO   (OVERSAMPLING),
    .CCSDS_TX_PHYS_SIG_QUANT_DEPTH (SIG_QUANT_DEPTH)
  ) u_ccsds_tx (
    .clk_i     (clk),
    .dat_par_i ({DATA_BUS_SIZE{1'b0}}),
    .dat_ser_i (1'b0),
    .dat_val_i (1'b0),
    .ena_i     (enable),
    .in_sel_i  (1'b0),                                 // parallel input
    .rst_i     (rst),
    .buf_ful_o (buf_ful),
    .clk_o     (clk_o_unused),
    .ena_o     (ena_o_unused),
    .idl_o     (idle),
    .sam_i_o   (sam_i),
    .sam_q_o   (sam_q),
    .sym_dbg_o (tx_sym_o),
    .flt_a_dbg_o (flt_a_o),
    .flt_b_dbg_o (flt_b_o)
  );

  //--------------------------------------------------------------------------
  // 8 -> 12 bit scaling with saturation, BPSK polarity, output registers
  //--------------------------------------------------------------------------
  function [DAC_WIDTH-1:0] scale_sample;
    input signed [SIG_QUANT_DEPTH-1:0] v;
    reg   signed [DAC_WIDTH:0]         wide;   // one guard bit for the shift
    begin
      wide = v;                                // sign extend
      if (INVERT_BPSK != 0)
        wide = -wide;
      wide = wide <<< SCALE_SHIFT;
      if (wide > (1 <<< (DAC_WIDTH-1)) - 1)
        scale_sample = {1'b0, {(DAC_WIDTH-1){1'b1}}};          // +full scale
      else if (wide < -(1 <<< (DAC_WIDTH-1)))
        scale_sample = {1'b1, {(DAC_WIDTH-1){1'b0}}};          // -full scale
      else
        scale_sample = wide[DAC_WIDTH-1:0];
    end
  endfunction

  reg [DAC_WIDTH-1:0] i_r = {DAC_WIDTH{1'b0}};
  reg [DAC_WIDTH-1:0] q_r = {DAC_WIDTH{1'b0}};

  always @(posedge clk) begin
    if (rst || !enable) begin
      i_r <= {DAC_WIDTH{1'b0}};
      q_r <= {DAC_WIDTH{1'b0}};
    end else begin
      i_r <= scale_sample(sam_i);
      q_r <= scale_sample(sam_q);   // BPSK: always 0, but keep the path real
    end
  end

  assign tx_i = (SWAP_IQ != 0) ? q_r : i_r;
  assign tx_q = (SWAP_IQ != 0) ? i_r : q_r;

  assign running = enable & ~rst;

  // 数字环回引出：把发射端真实的 8 位成形样点送给 ccsds_rx_lvds
  assign sam_i_o = sam_i;

endmodule
