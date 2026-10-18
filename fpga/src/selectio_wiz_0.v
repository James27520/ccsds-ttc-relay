//=============================================================================
// selectio_wiz_0.v -- primitive-only replacement for the selectio_wiz IP core.
//
// WHY
// ---
//   The vendor project (E:/7010_AD9363_SDR/Vivado2021.1工程/纯PL驱动/AD936X_only_PL.zip)
//   instantiates the Xilinx selectio_wiz IP in Src/data_process.v. That .xci is a
//   Vivado 2021.1 artifact and this board can only be built with 2018.3 (the one
//   installed Vivado that actually has the xc7z010clg400-1 part), so the IP has
//   to be reproduced. It turns out to be nothing more than 7 differential lanes
//   of DDR I/O, which is plain primitives, so this file replaces the IP entirely
//   and the design becomes RTL + primitives with no IP cores at all.
//
// ORIGINAL IP SETTINGS (selectio_wiz_0.xci)
// -----------------------------------------
//   C_INTERFACE_TYPE        NETWORKING
//   C_SYSTEM_DATA_WIDTH     7          (7 differential pairs)
//   C_DATA_RATE_STRING      2          (DDR)
//   C_SERIALIZATION_FACTOR  4
//   C_USE_SERIALIZATION     false      -> no ISERDES/OSERDES, just IDDR/ODDR
//   => device data width 14 = 7 pairs x 2 (DDR)
//
// BIT MAPPING -- derived from the vendor's own packing, not guessed
// ---------------------------------------------------------------
//   data_process.v, transmit side:
//       selectio_tx_data <= {tx_frame, tx0_msb_q, tx_frame, tx0_msb_i};   (14 bit)
//     so bit13 = frame, bits12:7 = q[5:0], bit6 = frame, bits5:0 = i[5:0].
//   data_process.v, receive side:
//       rx0_msb_i <= selectio_rx_data[05:0];
//       rx0_msb_q <= selectio_rx_data[12:7];
//
//   The frame bit appears at BOTH bit6 and bit13, which only works if pair k
//   carries device bits {k, k+7}:
//       pair0 -> i[0]/q[0] ... pair5 -> i[5]/q[5], pair6 -> frame/frame
//   The {2k, 2k+1} mapping would put q[5] on pair6 and contradicts the receive
//   unpacking, so {k, k+7} is the correct one. That is what this file uses.
//
// DDR edge convention
// -------------------
//   The vendor's AD936X_Driver.v uses DDR_CLK_EDGE "OPPOSITE_EDGE" for the same
//   interface, and selectio_wiz with DATA_RATE=2 on 7-series defaults to the
//   same mode, so OPPOSITE_EDGE is used here. Q1 is the rising-edge capture and
//   drives bit k, Q2 the falling-edge capture and drives bit k+7.
//=============================================================================

`timescale 1ns/100ps

module selectio_wiz_0 (
  // data lanes
  input  wire [6:0]  data_in_from_pins_p,
  input  wire [6:0]  data_in_from_pins_n,
  output wire [13:0] data_in_to_device,
  input  wire [13:0] data_out_from_device,
  output wire [6:0]  data_out_to_pins_p,
  output wire [6:0]  data_out_to_pins_n,
  // forwarded clock to the AD9361
  output wire        clk_to_pins_p,
  output wire        clk_to_pins_n,
  // source-synchronous receive clock from the AD9361
  input  wire        clk_in_p,
  input  wire        clk_in_n,
  output wire        clk_out,        // = data_clk = sample clock for the whole design
  input  wire        clk_reset,
  input  wire        io_reset
);

  //--------------------------------------------------------------------------
  // receive clock: differential in, single ended, onto a global buffer.
  // data_clk is the AD9361's DATA_CLK and is the sample clock of the design.
  //--------------------------------------------------------------------------
  wire clk_ibuf;
  IBUFDS ibuf_clk (
    .I  (clk_in_p),
    .IB (clk_in_n),
    .O  (clk_ibuf)
  );

  BUFG bufg_clk (
    .I (clk_ibuf),
    .O (clk_out)
  );

  //--------------------------------------------------------------------------
  // 7 DDR lanes
  //--------------------------------------------------------------------------
  genvar k;
  generate
    for (k = 0; k < 7; k = k + 1) begin : g_lane

      wire rx_single;
      IBUFDS ibuf_data (
        .I  (data_in_from_pins_p[k]),
        .IB (data_in_from_pins_n[k]),
        .O  (rx_single)
      );

      IDDR #(
        .DDR_CLK_EDGE ("OPPOSITE_EDGE"),
        .INIT_Q1      (1'b0),
        .INIT_Q2      (1'b0),
        .SRTYPE       ("SYNC")
      ) iddr_data (
        .Q1 (data_in_to_device[k]),      // rising edge  -> bit k
        .Q2 (data_in_to_device[k+7]),    // falling edge -> bit k+7
        .C  (clk_out),
        .CE (1'b1),
        .D  (rx_single),
        .R  (io_reset),
        .S  (1'b0)
      );

      wire tx_single;
      ODDR #(
        .DDR_CLK_EDGE ("OPPOSITE_EDGE"),
        .INIT         (1'b0),
        .SRTYPE       ("SYNC")
      ) oddr_data (
        .Q  (tx_single),
        .C  (clk_out),
        .CE (1'b1),
        .D1 (data_out_from_device[k]),      // rising edge  -> bit k
        .D2 (data_out_from_device[k+7]),    // falling edge -> bit k+7
        .R  (io_reset),
        .S  (1'b0)
      );

      OBUFDS obuf_data (
        .I  (tx_single),
        .O  (data_out_to_pins_p[k]),
        .OB (data_out_to_pins_n[k])
      );

    end
  endgenerate

  //--------------------------------------------------------------------------
  // forwarded clock: a DDR toggling ODDR gives one full period per data_clk
  // period with 50 % duty, which is what the AD9361 expects on TX_CLK.
  //--------------------------------------------------------------------------
  wire tx_clk_single;
  ODDR #(
    .DDR_CLK_EDGE ("OPPOSITE_EDGE"),
    .INIT         (1'b0),
    .SRTYPE       ("SYNC")
  ) oddr_clk (
    .Q  (tx_clk_single),
    .C  (clk_out),
    .CE (1'b1),
    .D1 (1'b0),
    .D2 (1'b1),
    .R  (io_reset),
    .S  (1'b0)
  );

  OBUFDS obuf_clk (
    .I  (tx_clk_single),
    .O  (clk_to_pins_p),
    .OB (clk_to_pins_n)
  );

  // clk_reset is kept for interface compatibility with the original IP; the
  // BUFG needs no reset and the IDDR/ODDR resets are driven by io_reset.
  wire unused_clk_reset = clk_reset;

endmodule
