//=============================================================================
// ccsds_tx_wrap.v -- glue between the euryspace VHDL CCSDS transmitter and the
//                    AD9363 CMOS 1R1T DAC pins of the 7010 telemetry board.
//
// What this module does
// ---------------------
//   1. Instantiates the euryspace VHDL ccsds_tx core. The frame source lives
//      inside the core: ccsds_tx_datalink_layer.vhd runs with
//      CCSDS_TX_DATALINK_STATIC_FRAME_ENABLED = true, bypassing the upstream
//      framer and driving the verified randomiser + rate-1/2 convolutional
//      coder + ASM inserter from one fixed CADU produced by the ground
//      reference. See that file for the measurements that motivated it.
//   2. Converts the core's 8 bit I/Q samples to the 12 bit AD9363 word,
//      applying the BPSK spectrum polarity the ground receiver expects.
//   3. Serialises I and Q onto the 12 DAC pins with ODDR primitives, in the
//      same format axi_ad9361_cmos_if uses.
//
// Why the sample clock is the DAC clock
// -------------------------------------
//   The AD9361 in CMOS 1R1T mode transfers a complete 12 bit I word on the
//   rising edge of DATA_CLK and the 12 bit Q word on the falling edge, so
//      sample rate == DATA_CLK == l_clk frequency.
//   ccsds_tx produces exactly one I/Q sample pair per clk_i, and its symbol
//   rate is clk_i / CCSDS_TX_OVERSAMPLING_RATIO. Running clk_i directly on the
//   AD9361 data clock therefore gives
//       sample rate  = 2.5 MSPS   (AD9363 configured at 2.5 MSPS)
//       symbol rate  = 250 ksym/s (oversampling ratio 10)
//   which is bit-for-bit the rate plan of the verified software link. It also
//   removes the 100 MHz -> tx_clk asynchronous FIFO the original porting plan
//   called for: there is no second clock domain at all.
//
// Pin format evidence (Vivado 2018.3 baseline, E:\7010_ttc_ccsds\pluto)
// ---------------------------------------------------------------------
//   bd/system/system.bd      : axi_ad9361 CMOS_OR_LVDS_N = 1  (1 = CMOS)
//                              axi_ad9361 MODE_1R1T       = 1
//   system_constr.xdc        : tx_data_out[11:0] on 12 single ended LVCMOS18
//                              pins, pairs (W14,Y14) (V12,W13) (Y18,Y19)
//                              (T12,U12) (Y16,Y17) (T11,T10)
//   axi_ad9361.v             : CMOS_OR_LVDS_N == 1 -> axi_ad9361_cmos_if
//   axi_ad9361_cmos_if.v     : dac_r1_mode = 1, dac_valid = 1
//                                tx_data_0_p <= dac_data[11:0]    (I, ch0)
//                                tx_data_1_p <= dac_data[23:12]   (Q, ch1)
//                              frame <= 2'b01
//   ad_data_out.v            : ODDR .D1(tx_data_n) .D2(tx_data_p)
//                              -> rising edge  = tx_data_0 = I
//                              -> falling edge = tx_data_1 = Q
//   axi_ad9361_tx.v          : channel 0 (Q_OR_I_N=0) drives dac_data_int_s[11:0]
//                              channel 1 (Q_OR_I_N=1) drives dac_data_int_s[23:12]
//   => rising = I[11:0], falling = Q[11:0], one I/Q pair per DATA_CLK cycle.
//   The earlier porting note ("12 bit I/Q occupies 2 DATA_CLK cycles, 6 bit
//   each") is the LVDS format and does not apply to this board.
//
// tx_frame_out is deliberately left to the ADI IP: we only replace the data
// lines, so the frame pattern the AD9361 already works with is untouched.
//=============================================================================

`timescale 1ns/100ps

module ccsds_tx_wrap #(
  // ---- CCSDS link configuration (must match the verified software link) ----
  parameter integer DATA_BUS_SIZE    = 16,      // datalink word width
  parameter integer OVERSAMPLING     = 10,      // samples per symbol
  parameter integer SIG_QUANT_DEPTH  = 8,       // core output width
  // ---- DAC interface ----
  parameter integer DAC_WIDTH        = 12,      // AD9363 sample width
  parameter integer SCALE_SHIFT      = 3,       // 8 -> 12 bit gain, 2^3 = 8
  // 0 = pass the core polarity through, 1 = invert the constellation.
  // The euryspace BPSK mapper sends bit 0 -> -full scale and bit 1 -> +full
  // scale (ccsds_tx_mapper_symbols_samples.vhd symbols_values(0) is negative,
  // symbols_values(1) is positive), while the verified ground link uses
  // bit 0 -> +1 (ccsds_tm_tx.py cadu_to_iq: np.where(bits == 0, 1.0, -1.0)).
  // Without this inversion every bit at the receiver is flipped and the
  // 0x1ACFFC1D ASM can never be found.
  parameter integer INVERT_BPSK      = 1
)(
  input  wire                    clk,        // AD9361 DATA_CLK (= l_clk, = sample rate)
  input  wire                    enable,     // 1 = CCSDS stream drives the DAC
  output wire [DAC_WIDTH-1:0]    dac_data,   // to the tx_data_out ODDR mux
  output wire                    buf_ful,    // debug: core input buffer full
  output wire                    idle,       // debug: framer inserted idle data
  output wire                    running     // debug: core out of reset and enabled
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
  // The frame source is inside the core: ccsds_tx_datalink_layer.vhd runs with
  // CCSDS_TX_DATALINK_STATIC_FRAME_ENABLED = true, so the upstream framer is
  // bypassed and the verified randomiser / rate-1/2 convolutional coder / ASM
  // inserter are driven from one fixed CADU built by the ground reference.
  // dat_par_i and dat_val_i therefore have no effect and are tied off.
  //--------------------------------------------------------------------------
  wire [SIG_QUANT_DEPTH-1:0] sam_i;
  wire [SIG_QUANT_DEPTH-1:0] sam_q;
  wire                       clk_o_unused;
  wire                       ena_o_unused;

  ccsds_tx #(
    .CCSDS_TX_BITS_PER_SYMBOL      (1),                 // BPSK
    .CCSDS_TX_BUFFER_SIZE          (16),
    .CCSDS_TX_MODULATION_TYPE      (2),                 // 2 = BPSK
    .CCSDS_TX_DATA_BUS_SIZE        (DATA_BUS_SIZE),
    .CCSDS_TX_OVERSAMPLING_RATIO   (OVERSAMPLING),
    .CCSDS_TX_PHYS_SIG_QUANT_DEPTH (SIG_QUANT_DEPTH)
  ) u_ccsds_tx (
    .clk_i     (clk),
    .dat_par_i ({DATA_BUS_SIZE{1'b0}}),
    .dat_ser_i (1'b0),
    .dat_val_i (1'b0),
    .ena_i     (enable),
    .in_sel_i  (1'b0),                                  // parallel input
    .rst_i     (rst),
    .buf_ful_o (buf_ful),
    .clk_o     (clk_o_unused),
    .ena_o     (ena_o_unused),
    .idl_o     (idle),
    .sam_i_o   (sam_i),
    .sam_q_o   (sam_q)
  );

  //--------------------------------------------------------------------------
  // 8 -> 12 bit scaling, BPSK polarity, output registers
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

  reg [DAC_WIDTH-1:0] dac_i_r = {DAC_WIDTH{1'b0}};
  reg [DAC_WIDTH-1:0] dac_q_r = {DAC_WIDTH{1'b0}};

  always @(posedge clk) begin
    if (rst || !enable) begin
      dac_i_r <= {DAC_WIDTH{1'b0}};
      dac_q_r <= {DAC_WIDTH{1'b0}};
    end else begin
      dac_i_r <= scale_sample(sam_i);
      dac_q_r <= scale_sample(sam_q);   // BPSK: always 0, but keep the path real
    end
  end

  //--------------------------------------------------------------------------
  // ODDR serialisation: rising edge carries I, falling edge carries Q
  // (same primitive configuration as ad_data_out.v used by the ADI IP)
  //--------------------------------------------------------------------------
  genvar gi;
  generate
    for (gi = 0; gi < DAC_WIDTH; gi = gi + 1) begin : g_dac_oddr
      ODDR #(
        .DDR_CLK_EDGE ("SAME_EDGE"),
        .INIT         (1'b0),
        .SRTYPE       ("SYNC")
      ) i_oddr (
        .Q  (dac_data[gi]),
        .C  (clk),
        .CE (1'b1),
        .D1 (dac_i_r[gi]),   // rising edge of clk  -> I
        .D2 (dac_q_r[gi]),   // falling edge of clk -> Q
        .R  (1'b0),
        .S  (1'b0)
      );
    end
  endgenerate

  assign running = enable & ~rst;

endmodule
