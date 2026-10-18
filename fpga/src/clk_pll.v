//=============================================================================
// clk_pll.v -- primitive-only replacement for the clk_wiz_0 IP core.
//
// The vendor project used the clk_wiz IP for this one function:
//     i_clk (50 MHz)  ->  100 MHz  +  locked
//     (clk_wiz_0.xci: PRIM_IN_FREQ 50.000, CLKOUT1_REQUESTED_OUT_FREQ 100.000,
//      PRIMITIVE MMCM, MMCM_CLKFBOUT_MULT_F 20.000, MMCM_CLKIN1_PERIOD 20.000,
//      MMCM_CLKOUT0_DIVIDE_F 10.000, USE_LOCKED 1, USE_RESET 0, NUM_OUT_CLKS 1)
//
// The IP exists only in a Vivado-version-specific form (the vendor's .xci is
// 2021.1 and this board must be built with 2018.3, the only installed Vivado
// that has the xc7z010clg400-1 part). Replacing it with an MMCME2_BASE removes
// the last IP dependency so the whole design is plain RTL plus primitives.
//
// 50 MHz in, VCO = 50 * 20 = 1000 MHz, out = 1000 / 10 = 100 MHz.
//
// WARNING about the feedback path: CLKFBOUT must go through a BUFG into
// CLKFBIN. Driving CLKFBOUT from the BUFG output (or omitting CLKFBIN) creates
// either a combinational loop or an unconnected feedback input, and the MMCM
// then never locks.
//=============================================================================

`timescale 1ns/100ps

module clk_pll (
  input  wire clk_in1,    // 50 MHz board clock
  output wire clk_out1,   // 100 MHz
  output wire locked
);

  wire clkfb_out;   // MMCM CLKFBOUT
  wire clkfb_in;    // back into CLKFBIN through a BUFG
  wire clk_out_raw;

  MMCME2_BASE #(
    .BANDWIDTH          ("OPTIMIZED"),
    .CLKFBOUT_MULT_F    (20.000),
    .CLKFBOUT_PHASE     (0.000),
    .CLKIN1_PERIOD      (20.000),        // 50 MHz
    .CLKOUT0_DIVIDE_F   (10.000),        // 1000 / 10 = 100 MHz
    .CLKOUT0_DUTY_CYCLE (0.500),
    .CLKOUT0_PHASE      (0.000),
    .DIVCLK_DIVIDE      (1),
    .REF_JITTER1        (0.010),
    .STARTUP_WAIT       ("FALSE")
  ) mmcm_i (
    .CLKOUT0   (clk_out_raw),
    .CLKOUT0B  (),
    .CLKOUT1   (), .CLKOUT1B (),
    .CLKOUT2   (), .CLKOUT2B (),
    .CLKOUT3   (), .CLKOUT3B (),
    .CLKOUT4   (), .CLKOUT5  (), .CLKOUT6 (),
    .CLKFBOUT  (clkfb_out),
    .CLKFBOUTB (),
    .CLKFBIN   (clkfb_in),
    .LOCKED    (locked),
    .CLKIN1    (clk_in1),
    .PWRDWN    (1'b0),
    .RST       (1'b0)
  );

  BUFG bufg_fb  (.I(clkfb_out),   .O(clkfb_in));
  BUFG bufg_out (.I(clk_out_raw), .O(clk_out1));

endmodule
