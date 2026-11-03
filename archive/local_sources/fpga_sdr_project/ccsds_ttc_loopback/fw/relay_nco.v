`timescale 1ns / 1ps
//=============================================================================
// relay_nco.v -- complex NCO for the relay DDC / DUC mixers
//
//   32-bit phase accumulator, 12-bit phase truncation, quarter-wave sine LUT.
//   Output amplitude: 12-bit signed, full scale 2047 == 1.0
//   Worst-case phase-truncation spur ~ -72 dBc, matched to the 12-bit data path.
//
//   LATENCY: exactly 2 clk.  cos_out / sin_out are valid two clock cycles
//   after `enable` is high, and correspond to the phase advanced BY that
//   enable pulse (i.e. to the sample presented on the same cycle).
//
//   freq_word: phase increment per sample.
//     f_out = freq_word / 2^32 * fs
//     e.g. fs = 30.72 MHz, want +100 kHz  ->  freq_word = 0x0028F5C3 (2684355)
//=============================================================================
module relay_nco (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               enable,       // advance one sample
    input  wire [31:0]        freq_word,
    output wire signed [11:0] cos_out,
    output wire signed [11:0] sin_out
);
    reg [31:0] phase_acc;

    wire [31:0] phase_cur = phase_acc;
    wire [31:0] phase_nxt = phase_cur + freq_word;
    // When enable is low the phase (and therefore the output) must hold.
    wire [31:0] phase_eff = enable ? phase_nxt : phase_cur;

    always @(posedge clk) begin
        if (!rst_n)            phase_acc <= 32'd0;
        else if (enable)       phase_acc <= phase_nxt;
    end

    wire [11:0] ph     = phase_eff[31:20];   // 12-bit phase: 0 .. 4095
    wire [1:0]  quad   = ph[11:10];          // quadrant 0..3
    wire [9:0]  amp_a  = ph[9:0];            // 0 .. 1023
    wire [9:0]  amp_b  = 10'd1023 - ph[9:0]; // mirror address 1023 .. 0

    wire [11:0] rom_a, rom_b;
    relay_sin_rom u_rom (
        .clk    (clk),
        .addr_a (amp_a),
        .addr_b (amp_b),
        .data_a (rom_a),
        .data_b (rom_b)
    );

    reg [1:0] quad_d;
    always @(posedge clk) begin
        if (!rst_n) quad_d <= 2'd0;
        else        quad_d <= quad;
    end

    // rom_a = S(amp_a) is the in-quadrant sine, rom_b = S(amp_b) the cosine.
    // Both are non-negative, so negating them cannot overflow 12-bit signed.
    wire signed [11:0] s_a = rom_a;
    wire signed [11:0] s_b = rom_b;

    reg signed [11:0] cos_r, sin_r;
    always @(*) begin
        case (quad_d)
            2'd0:    begin cos_r =  s_b; sin_r =  s_a; end
            2'd1:    begin cos_r = -s_a; sin_r =  s_b; end
            2'd2:    begin cos_r = -s_b; sin_r = -s_a; end
            default: begin cos_r =  s_a; sin_r = -s_b; end
        endcase
    end

    // Output register.  Without it the path becomes
    //   BRAM -> quadrant negation (carry chain) -> DSP48 input
    // which is far too long.  LATENCY is therefore 2 clocks:
    //   enable at cycle T  ->  cos_out/sin_out valid at cycle T+2.
    // dont_touch keeps this register out of the DSP48 input register:
    // without it Vivado absorbs it into the mixer's BREG and the path
    // becomes BRAM -> quadrant negate -> LUT -> DSP in a single cycle.
    (* dont_touch = "true" *) reg signed [11:0] cos_o;
    (* dont_touch = "true" *) reg signed [11:0] sin_o;
    always @(posedge clk) begin
        if (!rst_n) begin
            cos_o <= 12'sd0;
            sin_o <= 12'sd0;
        end else begin
            cos_o <= cos_r;
            sin_o <= sin_r;
        end
    end

    assign cos_out = cos_o;
    assign sin_out = sin_o;
endmodule
