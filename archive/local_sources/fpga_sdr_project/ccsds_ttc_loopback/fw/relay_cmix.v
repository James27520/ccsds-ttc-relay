`timescale 1ns / 1ps
//=============================================================================
// relay_cmix.v -- two-stage complex mixer
//
//   conj = 1 : y = x * (c - j*s)   used for the DDC (down-conversion)
//   conj = 0 : y = x * (c + j*s)   used for the DUC (up-conversion)
//
//   LATENCY = 2 clocks:  en at cycle T -> y valid at cycle T+2.
//   Stage 2 is enabled by `en` delayed one clock, i.e. the same pipeline slot.
//
//   Why two stages
//   --------------
//   The original single-stage version put everything in one clock:
//       ROM -> quadrant negate -> DSP multiply -> DSP cascade add -> saturate
//   which measured 12.0 ns and failed timing badly.  Splitting it means
//     stage 1 : FF -> DSP48 (MREG/PREG) -> FF
//     stage 2 : FF -> 25-bit carry add -> shift -> compare/saturate -> FF
//   so each stage has a few ns of margin even at the 4.069 ns that the vendor
//   XDC originally demanded.
//
//   Scaling: c and s are 12-bit signed with full scale 2047 == 1.0 for both
//   components of a unit phasor.  The product is shifted right by 11 so a
//   unity-amplitude NCO gives unity gain (2047*2047 >> 11 = 2046).
//=============================================================================
module relay_cmix (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               en,           // stage-1 valid (cycle T)
    input  wire               conj,
    input  wire signed [11:0] x_i,
    input  wire signed [11:0] x_q,
    input  wire signed [11:0] c,
    input  wire signed [11:0] s,
    output reg  signed [11:0] y_i,          // valid at cycle T+2
    output reg  signed [11:0] y_q,
    output reg                sat
);
    //------------------------------------------------------------------
    // stage 1 (T+1) : four 12x12 products, each individually registered
    //   registering each product lets the DSP48 use its internal MREG and
    //   PREG registers instead of chaining through PCOUT/PCIN
    //------------------------------------------------------------------
    reg signed [23:0] p_ic, p_qs, p_is, p_qc;

    always @(posedge clk) begin
        if (!rst_n) begin
            p_ic <= 24'sd0;
            p_qs <= 24'sd0;
            p_is <= 24'sd0;
            p_qc <= 24'sd0;
        end else if (en) begin
            p_ic <= x_i * c;
            p_qs <= x_q * s;
            p_is <= x_i * s;
            p_qc <= x_q * c;
        end
    end

    //------------------------------------------------------------------
    // stage 2 (T+2) : combine, normalise, saturate
    //------------------------------------------------------------------
    function signed [11:0] sat12;
        input signed [13:0] v;
        begin
            if      (v >  14'sd2047) sat12 =  12'sd2047;
            else if (v < -14'sd2048) sat12 = -12'sd2048;
            else                     sat12 =  v[11:0];
        end
    endfunction

    wire signed [24:0] p_ic_e = {p_ic[23], p_ic};
    wire signed [24:0] p_qs_e = {p_qs[23], p_qs};
    wire signed [24:0] p_is_e = {p_is[23], p_is};
    wire signed [24:0] p_qc_e = {p_qc[23], p_qc};

    wire signed [24:0] sum_i = conj ? (p_ic_e + p_qs_e) : (p_ic_e - p_qs_e);
    wire signed [24:0] sum_q = conj ? (p_qc_e - p_is_e) : (p_is_e + p_qc_e);

    wire signed [13:0] sh_i = sum_i >>> 11;
    wire signed [13:0] sh_q = sum_q >>> 11;

    wire ovi = (sh_i > 14'sd2047) || (sh_i < -14'sd2048);
    wire ovq = (sh_q > 14'sd2047) || (sh_q < -14'sd2048);

    reg en_d;
    always @(posedge clk) begin
        if (!rst_n) en_d <= 1'b0;
        else        en_d <= en;
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            y_i <= 12'sd0;
            y_q <= 12'sd0;
            sat <= 1'b0;
        end else if (en_d) begin
            y_i <= sat12(sh_i);
            y_q <= sat12(sh_q);
            sat <= ovi | ovq;
        end
    end
endmodule
