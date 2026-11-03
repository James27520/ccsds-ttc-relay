`timescale 1ns / 1ps
//=============================================================================
// relay_path.v -- one channel of the bent-pipe datapath (9-stage pipeline)
//
//   in_i/q --> [DDC mix] --> [DC block] --> [DUC mix] --> [gain] --> out_i/q
//
//   mode = 0  BYPASS  : out = in delayed by the pipeline depth
//   mode = 1  RELAY   : full DDC -> (DC block) -> DUC -> gain
//   mode = 2  MUTE    : out = 0
//   mode = 3  DUC_ONLY: DUC -> gain  (DDC and DC block bypassed)
//
//   Every mode has EXACTLY the same latency (9 clocks) so the DAC valid
//   timing never changes when software switches mode.
//
//   Pipeline / valid alignment (sample "s" enters on in_valid at cycle t).
//   relay_nco and relay_cmix each have a latency of 2 clocks.
//
//     t     in_valid  sample s presented; both NCOs advance
//     t+1   vld[0]    s_i/s_q           = sample s
//     t+2   vld[1]    bp0               NCO cos/sin(s); DDC products
//     t+3   vld[2]    bp1, n1           DDC stage 2
//     t+4   vld[3]    bp2, mix          DDC output
//     t+5   vld[4]    bp3, m_i/m_q      bypass mux, registered
//     t+6   vld[5]    bp4, d_i/d_q      DC blocker (dcv registered)
//     t+7   vld[6]    bp5, n4           DUC products; n4 = NCO(s)
//     t+8   vld[7]    bp6, duc          DUC stage 2
//     t+9   vld[8]    bp7, o_i/o_q      gain applied  -> out_valid
//
//   TIMING NOTES (this is why the pipeline is this deep):
//   * `mode` comes from a slow CDC register that fans out to every mux in both
//     channels.  Using it directly as a mux select produced a 189-load net with
//     2.1 ns of routing.  It is decoded into local registers first.
//   * m_i/m_q are registered so that the DC-blocker carry chain starts at a
//     nearby flip-flop instead of at that wide control net.
//   * relay_cmix is split into (multiply -> register) and
//     (carry add -> saturate -> register) so no stage holds both.
//
//   DSP48 usage: 4 (DDC) + 4 (DUC) + 2 (gain) = 10 per channel.
//   The DC blocker is multiplier-free (leaky-mean subtraction).
//=============================================================================
module relay_path #(
    parameter integer DC_K = 12          // DC blocker time constant = 2^DC_K samples
) (
    input  wire               clk,
    input  wire               rst_n,
    input  wire [1:0]         mode,
    input  wire               dc_en,
    input  wire [11:0]        gain_word,  // unsigned Q1.11 : 0x800 = 1.0
    input  wire signed [11:0] ddc_cos,    // down-conversion NCO (latency 2)
    input  wire signed [11:0] ddc_sin,
    input  wire signed [11:0] duc_cos,    // up-conversion NCO   (latency 2)
    input  wire signed [11:0] duc_sin,

    input  wire               in_valid,
    input  wire signed [11:0] in_i,
    input  wire signed [11:0] in_q,

    output wire               out_valid,
    output wire signed [11:0] out_i,
    output wire signed [11:0] out_q,
    output reg                clip_flag
);
    localparam [1:0] MODE_BYPASS = 2'd0;
    localparam [1:0] MODE_RELAY  = 2'd1;
    localparam [1:0] MODE_MUTE   = 2'd2;

    //------------------------------------------------------------------
    // decode `mode` into LOCAL registers.
    // `mode` is a static word from a CDC register with a very wide fanout;
    // using it combinationally as a mux select creates a long, sprawling net.
    //------------------------------------------------------------------
    reg ddc_on_r, dc_on_r, mute_r, bypass_r;
    always @(posedge clk) begin
        if (!rst_n) begin
            ddc_on_r <= 1'b0;
            dc_on_r  <= 1'b0;
            mute_r   <= 1'b1;          // safe: mute until told otherwise
            bypass_r <= 1'b0;
        end else begin
            ddc_on_r <= (mode == MODE_RELAY);
            dc_on_r  <= (mode == MODE_RELAY) && dc_en;
            mute_r   <= (mode == MODE_MUTE);
            bypass_r <= (mode == MODE_BYPASS);
        end
    end

    //------------------------------------------------------------------
    // valid pipeline : 9 stages
    //------------------------------------------------------------------
    reg [8:0] vld;
    always @(posedge clk) begin
        if (!rst_n) vld <= 9'd0;
        else        vld <= {vld[7:0], in_valid};
    end
    assign out_valid = vld[8];

    //------------------------------------------------------------------
    // t+1 (vld[0]) : register the input
    //------------------------------------------------------------------
    reg signed [11:0] s_i, s_q;
    always @(posedge clk) begin
        if (!rst_n) begin
            s_i <= 12'sd0;
            s_q <= 12'sd0;
        end else if (in_valid) begin
            s_i <= in_i;
            s_q <= in_q;
        end
    end

    //------------------------------------------------------------------
    // input sample carried along for the two bypass muxes
    //   bp0 valid at t+2 ... bp7 valid at t+9
    //------------------------------------------------------------------
    reg signed [11:0] bp_i0, bp_i1, bp_i2, bp_i3, bp_i4, bp_i5, bp_i6, bp_i7;
    reg signed [11:0] bp_q0, bp_q1, bp_q2, bp_q3, bp_q4, bp_q5, bp_q6, bp_q7;

    always @(posedge clk) begin
        if (!rst_n) begin
            bp_i0 <= 12'sd0; bp_i1 <= 12'sd0; bp_i2 <= 12'sd0; bp_i3 <= 12'sd0;
            bp_i4 <= 12'sd0; bp_i5 <= 12'sd0; bp_i6 <= 12'sd0; bp_i7 <= 12'sd0;
            bp_q0 <= 12'sd0; bp_q1 <= 12'sd0; bp_q2 <= 12'sd0; bp_q3 <= 12'sd0;
            bp_q4 <= 12'sd0; bp_q5 <= 12'sd0; bp_q6 <= 12'sd0; bp_q7 <= 12'sd0;
        end else begin
            if (vld[0]) begin bp_i0 <= s_i;    bp_q0 <= s_q;    end
            if (vld[1]) begin bp_i1 <= bp_i0;  bp_q1 <= bp_q0;  end
            if (vld[2]) begin bp_i2 <= bp_i1;  bp_q2 <= bp_q1;  end
            if (vld[3]) begin bp_i3 <= bp_i2;  bp_q3 <= bp_q2;  end
            if (vld[4]) begin bp_i4 <= bp_i3;  bp_q4 <= bp_q3;  end
            if (vld[5]) begin bp_i5 <= bp_i4;  bp_q5 <= bp_q4;  end
            if (vld[6]) begin bp_i6 <= bp_i5;  bp_q6 <= bp_q5;  end
            if (vld[7]) begin bp_i7 <= bp_i6;  bp_q7 <= bp_q6;  end
        end
    end

    //------------------------------------------------------------------
    // DDC (result valid at t+4, vld[3])
    //------------------------------------------------------------------
    wire signed [11:0] mix_i, mix_q;
    wire               mix_sat;

    relay_cmix u_ddc (
        .clk (clk), .rst_n (rst_n), .en (vld[1]), .conj (1'b1),
        .x_i (bp_i0), .x_q (bp_q0), .c (ddc_cos), .s (ddc_sin),
        .y_i (mix_i), .y_q (mix_q), .sat (mix_sat)
    );

    //------------------------------------------------------------------
    // t+5 (vld[4]) : DDC/DC-block bypass mux, REGISTERED
    //------------------------------------------------------------------
    reg signed [11:0] m_i, m_q;
    always @(posedge clk) begin
        if (!rst_n) begin
            m_i <= 12'sd0;
            m_q <= 12'sd0;
        end else if (vld[3]) begin
            m_i <= ddc_on_r ? mix_i : bp_i2;
            m_q <= ddc_on_r ? mix_q : bp_q2;
        end
    end

    //------------------------------------------------------------------
    // t+6 (vld[5]) : DC blocker, multiplier free
    //   mean[n] = mean[n-1] + (x[n] - mean[n-1]) >>> K
    //   y[n]    = x[n] - mean[n-1]
    //------------------------------------------------------------------
    function signed [11:0] sat12_17;
        input signed [16:0] v;
        begin
            if      (v >  17'sd2047) sat12_17 =  12'sd2047;
            else if (v < -17'sd2048) sat12_17 = -12'sd2048;
            else                     sat12_17 =  v[11:0];
        end
    endfunction

    reg signed [16:0] mean_i, mean_q;
    wire signed [16:0] mi_e = {{5{m_i[11]}}, m_i};
    wire signed [16:0] mq_e = {{5{m_q[11]}}, m_q};
    wire signed [16:0] dcv_i = mi_e - mean_i;
    wire signed [16:0] dcv_q = mq_e - mean_q;

    reg signed [11:0] d_i, d_q;
    always @(posedge clk) begin
        if (!rst_n) begin
            mean_i <= 17'sd0;
            mean_q <= 17'sd0;
            d_i    <= 12'sd0;
            d_q    <= 12'sd0;
        end else if (vld[4]) begin
            if (dc_on_r) begin
                mean_i <= mean_i + (dcv_i >>> DC_K);
                mean_q <= mean_q + (dcv_q >>> DC_K);
                d_i    <= sat12_17(dcv_i);
                d_q    <= sat12_17(dcv_q);
            end else begin
                d_i    <= m_i;
                d_q    <= m_q;
            end
        end
    end

    //------------------------------------------------------------------
    // DUC NCO alignment: NCO(s) is valid at t+2, needed at t+6 (cmix2 en)
    //------------------------------------------------------------------
    reg signed [11:0] n1c, n1s, n2c, n2s, n3c, n3s, n4c, n4s;
    always @(posedge clk) begin
        if (!rst_n) begin
            n1c <= 12'sd0; n1s <= 12'sd0;
            n2c <= 12'sd0; n2s <= 12'sd0;
            n3c <= 12'sd0; n3s <= 12'sd0;
            n4c <= 12'sd0; n4s <= 12'sd0;
        end else begin
            if (vld[1]) begin n1c <= duc_cos; n1s <= duc_sin; end
            if (vld[2]) begin n2c <= n1c;     n2s <= n1s;     end
            if (vld[3]) begin n3c <= n2c;     n3s <= n2s;     end
            if (vld[4]) begin n4c <= n3c;     n4s <= n3s;     end
        end
    end

    //------------------------------------------------------------------
    // DUC (result valid at t+8, vld[7])
    //------------------------------------------------------------------
    wire signed [11:0] duc_i, duc_q;
    wire               duc_sat;

    relay_cmix u_duc (
        .clk (clk), .rst_n (rst_n), .en (vld[5]), .conj (1'b0),
        .x_i (d_i), .x_q (d_q), .c (n4c), .s (n4s),
        .y_i (duc_i), .y_q (duc_q), .sat (duc_sat)
    );

    // carry the DDC saturation flag from t+4 to t+8
    reg sat_p0, sat_p1, sat_p2, sat_p3;
    always @(posedge clk) begin
        if (!rst_n) begin
            sat_p0 <= 1'b0; sat_p1 <= 1'b0; sat_p2 <= 1'b0; sat_p3 <= 1'b0;
        end else begin
            if (vld[3]) sat_p0 <= mix_sat;
            if (vld[4]) sat_p1 <= sat_p0;
            if (vld[5]) sat_p2 <= sat_p1;
            if (vld[6]) sat_p3 <= sat_p2;
        end
    end

    //------------------------------------------------------------------
    // t+9 (vld[8]) : digital gain, Q1.11, saturating
    //------------------------------------------------------------------
    wire signed [12:0] gain_ext = $signed({1'b0, gain_word});   // 0 .. 4095
    wire signed [24:0] gp_i = duc_i * gain_ext;
    wire signed [24:0] gp_q = duc_q * gain_ext;
    wire signed [13:0] gsh_i = gp_i >>> 11;
    wire signed [13:0] gsh_q = gp_q >>> 11;

    wire gov_i = (gsh_i > 14'sd2047) || (gsh_i < -14'sd2048);
    wire gov_q = (gsh_q > 14'sd2047) || (gsh_q < -14'sd2048);

    function signed [11:0] sat12_14;
        input signed [13:0] v;
        begin
            if      (v >  14'sd2047) sat12_14 =  12'sd2047;
            else if (v < -14'sd2048) sat12_14 = -12'sd2048;
            else                     sat12_14 =  v[11:0];
        end
    endfunction

    reg signed [11:0] o_i, o_q;
    always @(posedge clk) begin
        if (!rst_n) begin
            o_i <= 12'sd0;
            o_q <= 12'sd0;
        end else if (vld[7]) begin
            o_i <= sat12_14(gsh_i);
            o_q <= sat12_14(gsh_q);
        end
    end

    // clip pulse, aligned with out_valid
    always @(posedge clk) begin
        if (!rst_n)      clip_flag <= 1'b0;
        else if (vld[7]) clip_flag <= sat_p3 | duc_sat | gov_i | gov_q;
        else             clip_flag <= 1'b0;
    end

    //------------------------------------------------------------------
    // output mux
    //------------------------------------------------------------------
    assign out_i = mute_r   ? 12'sd0  :
                   bypass_r ? bp_i7   : o_i;
    assign out_q = mute_r   ? 12'sd0  :
                   bypass_r ? bp_q7   : o_q;

endmodule
