`timescale 1ns / 1ps
//=============================================================================
// relay_dq.v -- PL bent-pipe relay core  (IoT-NTN satellite transponder)
//
//   adc_data_d1/q1 --> relay_path(ch1) --+
//   adc_data_d2/q2 --> relay_path(ch2) --+--> dac_data_d1/q1/d2/q2 + dac_valid
//
//   Replaces dds_dq_0 in design_1: the DAC port of ad9361_phy_0 is driven by
//   this module instead of by the DDS tone generator.
//
//   Clocking
//   --------
//   Everything in the datapath runs on dq_data_clk = ad9361_phy_0/data_clk.
//   ADC data, DAC data and the NCO are all in that one domain, so there is no
//   data-path clock crossing at all.  Only the AXI-Lite control/status words
//   cross (raxi_clk -> dq_data_clk and back), handled by relay_cdc.v.
//
//   DAC valid pacing (matches phy_tx's own sequencing counter)
//   ---------------------------------------------------------
//   phy_tx serialises dac_data_d1/q1/d2/q2 at 2 data_clk per sample in 1R1T
//   and 4 data_clk per sample in 2R2T, latching all four inputs on dac_valid.
//   phy_rx asserts adc_d1q1_valid exactly once per TX sequence period
//   (1-in-2 in 1R1T, 1-in-4 in 2R2T), so dac_valid is derived directly from
//   the relayed ch1 valid - no extra pacing counter is needed.
//
//   In 1R1T adc_d2q2_valid is never asserted (phy_rx gates it with
//   phy_mode==2R2T); phy_tx also only uses d1/q1 in 1R1T, so ch2 may sit idle.
//
//   Frequency word
//   --------------
//     f_offset = freq_word / 2^32 * fs
//     Net translation of the relay = (duc_freq - ddc_freq)/2^32 * fs
//     Example: fs = 30.72 MHz, want -100 kHz  ->  freq_word = 0xFFD70A3D
//=============================================================================
module relay_dq #(
    // diagnostic counter snapshot period, in ch1 samples.
    // 4096 samples = 133 us at 30.72 MSPS, so a status read is never more
    // than that stale while still being a coherent (non-torn) value.
    parameter integer SNAP_PERIOD = 4096
) (
    // ---------------- data clock domain ----------------
    input  wire        dq_data_clk,
    input  wire        rst_n,              // async reset source (AXI domain ok)

    // from ad9361_phy_0  (ADC side)
    input  wire        adc_d1q1_valid,
    input  wire [11:0] adc_data_d1,
    input  wire [11:0] adc_data_q1,
    input  wire        adc_d2q2_valid,
    input  wire [11:0] adc_data_d2,
    input  wire [11:0] adc_data_q2,

    // to ad9361_phy_0  (DAC side)
    output reg         dac_valid,
    output reg  [11:0] dac_data_d1,
    output reg  [11:0] dac_data_q1,
    output reg  [11:0] dac_data_d2,
    output reg  [11:0] dac_data_q2,

    // static mode pin, same signal that drives ad9361_phy_0/phy_mode
    input  wire        phy_mode,           // 1 = 1R1T , 0 = 2R2T

    // ---------------- AXI clock domain ----------------
    input  wire        raxi_clk,
    // ---- channel 1 : feeder uplink -> user downlink ----
    input  wire [1:0]  ctrl_mode,          // 0 bypass 1 relay 2 mute 3 duc_only
    input  wire        ctrl_dc_en,         // DC blocker enable (relay mode only)
    input  wire [11:0] ctrl_gain,          // unsigned Q1.11, 0x800 = 1.0
    input  wire [31:0] ctrl_ddc_freq,
    input  wire [31:0] ctrl_duc_freq,
    // ---- channel 2 : user uplink -> feeder downlink ----
    input  wire [1:0]  ctrl_mode2,
    input  wire        ctrl_dc_en2,
    input  wire [11:0] ctrl_gain2,
    input  wire [31:0] ctrl_ddc_freq2,
    input  wire [31:0] ctrl_duc_freq2,

    output wire [31:0] status_sample_cnt,  // adc ch1 samples seen
    output wire [31:0] status_clip_cnt,    // saturation events (both channels)
    output wire [31:0] status_out_cnt,     // dac_valid pulses issued
    output wire [31:0] status_sample_cnt2, // adc ch2 samples seen
    output wire [31:0] status_clip_cnt2    // ch2 saturation events
);

    //=================================================================
    // reset : async assert, synchronous de-assert in the data domain
    //=================================================================
    wire dclk_rst_n;
    relay_reset_sync u_rst (
        .clk       (dq_data_clk),
        .arst_n_in (rst_n),
        .rst_n_out (dclk_rst_n)
    );

    //=================================================================
    // control word clock crossing : raxi_clk -> dq_data_clk
    //=================================================================
    wire [1:0]  mode_s;
    wire        dc_en_s;
    wire [11:0] gain_s;
    wire [31:0] ddc_fw_s;
    wire [31:0] duc_fw_s;

    relay_cdc_word #(.WIDTH(2),  .STABLE_CYCLES(4)) u_cdc_mode (
        .src_clk(raxi_clk), .src_word(ctrl_mode),
        .dst_clk(dq_data_clk), .dst_rst_n(dclk_rst_n), .dst_word(mode_s));

    relay_cdc_word #(.WIDTH(1),  .STABLE_CYCLES(4)) u_cdc_dcen (
        .src_clk(raxi_clk), .src_word(ctrl_dc_en),
        .dst_clk(dq_data_clk), .dst_rst_n(dclk_rst_n), .dst_word(dc_en_s));

    relay_cdc_word #(.WIDTH(12), .STABLE_CYCLES(4)) u_cdc_gain (
        .src_clk(raxi_clk), .src_word(ctrl_gain),
        .dst_clk(dq_data_clk), .dst_rst_n(dclk_rst_n), .dst_word(gain_s));

    relay_cdc_word #(.WIDTH(32), .STABLE_CYCLES(4)) u_cdc_ddc (
        .src_clk(raxi_clk), .src_word(ctrl_ddc_freq),
        .dst_clk(dq_data_clk), .dst_rst_n(dclk_rst_n), .dst_word(ddc_fw_s));

    relay_cdc_word #(.WIDTH(32), .STABLE_CYCLES(4)) u_cdc_duc (
        .src_clk(raxi_clk), .src_word(ctrl_duc_freq),
        .dst_clk(dq_data_clk), .dst_rst_n(dclk_rst_n), .dst_word(duc_fw_s));

    // ---- channel 2 control words ----
    wire [1:0]  mode2_s;
    wire        dc_en2_s;
    wire [11:0] gain2_s;
    wire [31:0] ddc_fw2_s;
    wire [31:0] duc_fw2_s;

    relay_cdc_word #(.WIDTH(2),  .STABLE_CYCLES(4)) u_cdc_mode2 (
        .src_clk(raxi_clk), .src_word(ctrl_mode2),
        .dst_clk(dq_data_clk), .dst_rst_n(dclk_rst_n), .dst_word(mode2_s));

    relay_cdc_word #(.WIDTH(1),  .STABLE_CYCLES(4)) u_cdc_dcen2 (
        .src_clk(raxi_clk), .src_word(ctrl_dc_en2),
        .dst_clk(dq_data_clk), .dst_rst_n(dclk_rst_n), .dst_word(dc_en2_s));

    relay_cdc_word #(.WIDTH(12), .STABLE_CYCLES(4)) u_cdc_gain2 (
        .src_clk(raxi_clk), .src_word(ctrl_gain2),
        .dst_clk(dq_data_clk), .dst_rst_n(dclk_rst_n), .dst_word(gain2_s));

    relay_cdc_word #(.WIDTH(32), .STABLE_CYCLES(4)) u_cdc_ddc2 (
        .src_clk(raxi_clk), .src_word(ctrl_ddc_freq2),
        .dst_clk(dq_data_clk), .dst_rst_n(dclk_rst_n), .dst_word(ddc_fw2_s));

    relay_cdc_word #(.WIDTH(32), .STABLE_CYCLES(4)) u_cdc_duc2 (
        .src_clk(raxi_clk), .src_word(ctrl_duc_freq2),
        .dst_clk(dq_data_clk), .dst_rst_n(dclk_rst_n), .dst_word(duc_fw2_s));

    //=================================================================
    // NCOs.  Each channel owns its own DDC/DUC pair so the two links can
    // carry independent fine frequency offsets (e.g. per-link Doppler).
    // ch1 NCO advances on adc_d1q1_valid, ch2 NCO on adc_d2q2_valid -
    // in 2R2T these are asserted on different clocks of the 4-clock frame,
    // so each channel's phase advances exactly once per own sample.
    //=================================================================
    wire signed [11:0] ddc_cos,   ddc_sin,   duc_cos,   duc_sin;
    wire signed [11:0] ddc_cos2,  ddc_sin2,  duc_cos2,  duc_sin2;

    relay_nco u_nco_ddc (
        .clk(dq_data_clk), .rst_n(dclk_rst_n), .enable(adc_d1q1_valid),
        .freq_word(ddc_fw_s), .cos_out(ddc_cos), .sin_out(ddc_sin));

    relay_nco u_nco_duc (
        .clk(dq_data_clk), .rst_n(dclk_rst_n), .enable(adc_d1q1_valid),
        .freq_word(duc_fw_s), .cos_out(duc_cos), .sin_out(duc_sin));

    relay_nco u_nco_ddc2 (
        .clk(dq_data_clk), .rst_n(dclk_rst_n), .enable(adc_d2q2_valid),
        .freq_word(ddc_fw2_s), .cos_out(ddc_cos2), .sin_out(ddc_sin2));

    relay_nco u_nco_duc2 (
        .clk(dq_data_clk), .rst_n(dclk_rst_n), .enable(adc_d2q2_valid),
        .freq_word(duc_fw2_s), .cos_out(duc_cos2), .sin_out(duc_sin2));

    //=================================================================
    // two datapath channels
    //=================================================================
    wire               v1, v2;
    wire signed [11:0] o1_i, o1_q, o2_i, o2_q;
    wire               c1_flag, c2_flag;

    relay_path u_path_ch1 (
        .clk(dq_data_clk), .rst_n(dclk_rst_n),
        .mode(mode_s), .dc_en(dc_en_s), .gain_word(gain_s),
        .ddc_cos(ddc_cos), .ddc_sin(ddc_sin),
        .duc_cos(duc_cos), .duc_sin(duc_sin),
        .in_valid(adc_d1q1_valid), .in_i(adc_data_d1), .in_q(adc_data_q1),
        .out_valid(v1), .out_i(o1_i), .out_q(o1_q), .clip_flag(c1_flag));

    relay_path u_path_ch2 (
        .clk(dq_data_clk), .rst_n(dclk_rst_n),
        .mode(mode2_s), .dc_en(dc_en2_s), .gain_word(gain2_s),
        .ddc_cos(ddc_cos2), .ddc_sin(ddc_sin2),
        .duc_cos(duc_cos2), .duc_sin(duc_sin2),
        .in_valid(adc_d2q2_valid), .in_i(adc_data_d2), .in_q(adc_data_q2),
        .out_valid(v2), .out_i(o2_i), .out_q(o2_q), .clip_flag(c2_flag));

    //=================================================================
    // DAC output register : dac_valid follows ch1's out_valid by 1 clk
    //=================================================================
    always @(posedge dq_data_clk) begin
        if (!dclk_rst_n) begin
            dac_valid   <= 1'b0;
            dac_data_d1 <= 12'sd0;
            dac_data_q1 <= 12'sd0;
            dac_data_d2 <= 12'sd0;
            dac_data_q2 <= 12'sd0;
        end else begin
            dac_valid   <= v1;
            dac_data_d1 <= o1_i;
            dac_data_q1 <= o1_q;
            dac_data_d2 <= o2_i;
            dac_data_q2 <= o2_q;
        end
    end

    //=================================================================
    // diagnostic counters (data domain) + snapshot to the AXI domain
    //=================================================================
    reg [31:0] sample_cnt;
    reg [31:0] clip_cnt;
    reg [31:0] out_cnt;
    reg [31:0] sample_cnt2;
    reg [31:0] clip_cnt2;

    wire clip_ev  = (v1 & c1_flag) | (v2 & c2_flag);
    wire clip2_ev = (v2 & c2_flag);

    always @(posedge dq_data_clk) begin
        if (!dclk_rst_n) begin
            sample_cnt  <= 32'd0;
            clip_cnt    <= 32'd0;
            out_cnt     <= 32'd0;
            sample_cnt2 <= 32'd0;
            clip_cnt2   <= 32'd0;
        end else begin
            if (adc_d1q1_valid) sample_cnt  <= sample_cnt  + 32'd1;
            if (adc_d2q2_valid) sample_cnt2 <= sample_cnt2 + 32'd1;
            if (clip_ev)        clip_cnt    <= clip_cnt    + 32'd1;
            if (clip2_ev)       clip_cnt2   <= clip_cnt2   + 32'd1;
            if (dac_valid)      out_cnt     <= out_cnt     + 32'd1;
        end
    end

    relay_counter_snap #(.SNAP_PERIOD(SNAP_PERIOD)) u_snap (
        .dclk(dq_data_clk), .dclk_rst_n(dclk_rst_n), .dclk_inc(adc_d1q1_valid),
        .cnt_a(sample_cnt), .cnt_b(clip_cnt), .cnt_c(out_cnt),
        .raxi_clk(raxi_clk), .raxi_rst_n(rst_n),
        .out_a(status_sample_cnt), .out_b(status_clip_cnt), .out_c(status_out_cnt));

    relay_counter_snap #(.SNAP_PERIOD(SNAP_PERIOD)) u_snap2 (
        .dclk(dq_data_clk), .dclk_rst_n(dclk_rst_n), .dclk_inc(adc_d2q2_valid),
        .cnt_a(sample_cnt2), .cnt_b(clip_cnt2), .cnt_c(32'd0),
        .raxi_clk(raxi_clk), .raxi_rst_n(rst_n),
        .out_a(status_sample_cnt2), .out_b(status_clip_cnt2), .out_c());

    // phy_mode is a static configuration pin; keep it referenced so the
    // synthesiser does not drop the port.
    wire unused_phy_mode = phy_mode;

endmodule
