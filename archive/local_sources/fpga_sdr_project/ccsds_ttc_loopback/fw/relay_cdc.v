`timescale 1ns / 1ps
//=============================================================================
// relay_cdc.v -- clock-domain-crossing helpers for the relay datapath
//
//   relay_reset_sync  : async-assert / sync-deassert reset for a new clock domain
//   relay_cdc_word    : multi-bit control word from AXI clock -> data_clk
//   relay_counter_snap: 32-bit diagnostic counters from data_clk -> AXI clock
//
// raxi_clk  = AXI-Lite clock  (PS FCLK_CLK0, 100 MHz)
// dclk      = data_clk        (= ad9361_phy_0/data_clk, = sample rate in 1R1T)
//
// Why a stability filter instead of a handshake for relay_cdc_word:
//   these words (mode / frequency / gain) are written by software a few times
//   per second. A 2-flop synchroniser alone can latch a value that is torn
//   mid-transition. Requiring the synchronised value to be unchanged for
//   STABLE_CYCLES data_clk cycles makes a torn capture practically impossible,
//   costs nothing at run time, and needs no protocol on the writer side.
//=============================================================================

//-----------------------------------------------------------------------------
// Async assert, synchronous de-assert. Use the output as the reset for all
// logic running on `clk`.
//-----------------------------------------------------------------------------
module relay_reset_sync (
    input  wire clk,
    input  wire arst_n_in,      // asynchronous reset source, active low
    output wire rst_n_out       // reset synchronised to clk
);
    reg [1:0] sync;

    always @(posedge clk or negedge arst_n_in) begin
        if (!arst_n_in) sync <= 2'b00;
        else            sync <= {sync[0], 1'b1};
    end

    assign rst_n_out = sync[1];
endmodule


//-----------------------------------------------------------------------------
// Multi-bit control word: src_clk -> dst_clk, with stability filter.
//-----------------------------------------------------------------------------
module relay_cdc_word #(
    parameter integer WIDTH         = 16,
    parameter integer STABLE_CYCLES = 4     // must be >= 2
) (
    input  wire             src_clk,
    input  wire [WIDTH-1:0] src_word,
    input  wire             dst_clk,
    input  wire             dst_rst_n,
    output reg  [WIDTH-1:0] dst_word
);
    // src_clk is only used to give the tool a defined launching clock.
    (* ASYNC_REG = "TRUE" *) reg [WIDTH-1:0] sync0;
    (* ASYNC_REG = "TRUE" *) reg [WIDTH-1:0] sync1;
    reg [WIDTH-1:0] sync1_d;
    reg [3:0]       stable_cnt;

    always @(posedge dst_clk) begin
        sync0   <= src_word;
        sync1   <= sync0;
        sync1_d <= sync1;
    end

    always @(posedge dst_clk) begin
        if (!dst_rst_n) begin
            stable_cnt <= 4'd0;
            dst_word   <= {WIDTH{1'b0}};
        end else if (sync1 != sync1_d) begin
            stable_cnt <= 4'd0;                 // value still moving, restart
        end else if (stable_cnt < STABLE_CYCLES[3:0]) begin
            stable_cnt <= stable_cnt + 4'd1;
        end else begin
            dst_word <= sync1;                  // stable long enough, accept
        end
    end

    // keep src_clk in the sensitivity list of the design (documentation only)
    wire unused_src_clk = src_clk;
endmodule


//-----------------------------------------------------------------------------
// 32-bit diagnostic counter snapshot: data_clk -> AXI clock.
//
// A free-running counter cannot be read coherently across clock domains. This
// module instead publishes a *snapshot*: every SNAP_PERIOD samples the
// data_clk side latches all counters into a shadow register and toggles a flag,
// and the AXI side copies the shadow when it sees the flag change. The worst
// case staleness is SNAP_PERIOD samples (a fraction of a millisecond), and the
// value read is always internally consistent - no torn reads.
//-----------------------------------------------------------------------------
module relay_counter_snap #(
    parameter integer SNAP_PERIOD = 4096    // in samples of the source domain
) (
    input  wire        dclk,
    input  wire        dclk_rst_n,
    input  wire        dclk_inc,            // pulse once per sample
    input  wire [31:0] cnt_a,
    input  wire [31:0] cnt_b,
    input  wire [31:0] cnt_c,

    input  wire        raxi_clk,
    input  wire        raxi_rst_n,
    output reg  [31:0] out_a,
    output reg  [31:0] out_b,
    output reg  [31:0] out_c
);
    reg [15:0] prescale;
    reg [31:0] sh_a, sh_b, sh_c;
    reg        sh_toggle;

    // ---- source domain: periodic snapshot ----
    always @(posedge dclk) begin
        if (!dclk_rst_n) begin
            prescale  <= 16'd0;
            sh_a      <= 32'd0;
            sh_b      <= 32'd0;
            sh_c      <= 32'd0;
            sh_toggle <= 1'b0;
        end else if (dclk_inc) begin
            if (prescale == SNAP_PERIOD[15:0] - 16'd1) begin
                prescale  <= 16'd0;
                sh_a      <= cnt_a;
                sh_b      <= cnt_b;
                sh_c      <= cnt_c;
                sh_toggle <= ~sh_toggle;
            end else begin
                prescale <= prescale + 16'd1;
            end
        end
    end

    // ---- destination domain: copy when the toggle moves ----
    (* ASYNC_REG = "TRUE" *) reg tgl0, tgl1, tgl2;

    always @(posedge raxi_clk) begin
        tgl0 <= sh_toggle;
        tgl1 <= tgl0;
        tgl2 <= tgl1;
    end

    always @(posedge raxi_clk) begin
        if (!raxi_rst_n) begin
            out_a <= 32'd0;
            out_b <= 32'd0;
            out_c <= 32'd0;
        end else if (tgl1 != tgl2) begin
            // sh_* is stable: the source only changes it together with the
            // toggle, and we are at least two destination clocks behind it.
            out_a <= sh_a;
            out_b <= sh_b;
            out_c <= sh_c;
        end
    end
endmodule
