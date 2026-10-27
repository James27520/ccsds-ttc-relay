// AD9643 DDR8 training, ADC A PN9 (0D=06), B checker (0D=04), both 14=05.
// words[13:0] is the earliest word; each vector contains four A/four B words.
// The test-only A XOR must NEVER be inserted into the normal ADC data path.
// PN packing follows ADI hdl_2016_r1 axi_ad9643_pnmon.v: 15 PN bits per
// ADC word, of which the lower 14 are transmitted. It is not a 14-bit step.
module tc_pn9_train(
    input wire clk_vec,
    input wire reset,
    input wire restart,
    input wire enable,
    input wire invalidate,
    input wire [111:0] words,
    output reg valid,
    output reg parity,
    output reg failed,
    output reg [15:0] good_vectors
);
    localparam [15:0] REQUIRED_VECTORS = 16'd128;
    reg [13:0] previous_a [0:1];
    reg [13:0] previous_b [0:1];
    reg [1:0] have_previous;
    reg [15:0] count [0:1];
    reg [13:0] coverage [0:1];
    wire [13:0] last_a [0:1];
    wire [13:0] last_b [0:1];
    wire [1:0] intra_ok;
    wire [1:0] stream_ok;
    wire [1:0] qualifies;
    reg [15:0] next_count [0:1];
    reg [13:0] next_coverage [0:1];

    function [13:0] pn9_next;
        input [13:0] previous_word;
        reg [8:0] state;
        reg [14:0] generated;
        reg bit_next;
        integer bit_index;
        begin
            state = previous_word[8:0];
            generated = 15'b0;
            for (bit_index = 0; bit_index < 15; bit_index = bit_index + 1) begin
                bit_next = state[8] ^ state[4];
                state = {state[7:0], bit_next};
                generated = {generated[13:0], bit_next};
            end
            pn9_next = generated[13:0];
        end
    endfunction

    function checker_word;
        input [13:0] value;
        begin checker_word = (value == 14'h1555) || (value == 14'h2aaa); end
    endfunction

    function pn9_word_valid;
        input [13:0] value;
        integer bit_index;
        begin
            // All 14 transmitted bits are consecutive PN bits. These five
            // relations check the upper bits even on the first observed word,
            // where there is no preceding sample to predict it from.
            pn9_word_valid = (value[8:0] != 0);
            for (bit_index = 0; bit_index < 5; bit_index = bit_index + 1)
                pn9_word_valid = pn9_word_valid &&
                    (value[bit_index] == (value[bit_index+9] ^ value[bit_index+5]));
        end
    endfunction

    genvar candidate;
    generate for (candidate = 0; candidate < 2; candidate = candidate + 1) begin: candidates
        wire [13:0] a [0:3];
        wire [13:0] b [0:3];
        wire [13:0] local_coverage;
        wire boundary_ok;
        genvar sample_index;
        for (sample_index = 0; sample_index < 4; sample_index = sample_index + 1) begin: samples
            assign a[sample_index] = words[14*(2*sample_index+candidate) +: 14] ^ 14'h3fff;
            assign b[sample_index] = words[14*(2*sample_index+1-candidate) +: 14];
        end
        assign last_a[candidate] = a[3];
        assign last_b[candidate] = b[3];
        assign intra_ok[candidate] =
            pn9_word_valid(a[0]) && pn9_word_valid(a[1]) &&
            pn9_word_valid(a[2]) && pn9_word_valid(a[3]) &&
            (pn9_next(a[0]) == a[1]) && (pn9_next(a[1]) == a[2]) &&
            (pn9_next(a[2]) == a[3]) &&
            checker_word(b[0]) && checker_word(b[1]) &&
            checker_word(b[2]) && checker_word(b[3]) &&
            ((b[0] ^ b[1]) == 14'h3fff) && ((b[1] ^ b[2]) == 14'h3fff) &&
            ((b[2] ^ b[3]) == 14'h3fff);
        assign local_coverage = (a[0] ^ a[1]) | (a[1] ^ a[2]) | (a[2] ^ a[3]);
        assign boundary_ok = (pn9_next(previous_a[candidate]) == a[0]) &&
                             ((previous_b[candidate] ^ b[0]) == 14'h3fff);
        assign stream_ok[candidate] = intra_ok[candidate] &&
                                     (!have_previous[candidate] || boundary_ok);
        always @* begin
            next_count[candidate] = 0;
            next_coverage[candidate] = 0;
            if (intra_ok[candidate]) begin
                // A discontinuity before lock starts a NEW contiguous window.
                next_count[candidate] = 1;
                next_coverage[candidate] = local_coverage;
                if (have_previous[candidate] && boundary_ok && count[candidate] != 0) begin
                    next_count[candidate] = (count[candidate] < REQUIRED_VECTORS) ?
                                            count[candidate] + 1'b1 : REQUIRED_VECTORS;
                    next_coverage[candidate] = coverage[candidate] | local_coverage |
                                              (previous_a[candidate] ^ a[0]);
                end
            end
        end
        assign qualifies[candidate] = (next_count[candidate] == REQUIRED_VECTORS) &&
                                      (next_coverage[candidate] == 14'h3fff);
    end endgenerate

    integer p;
    // reset may assert with stopped CLKDIV; its deassertion must be synchronized
    // by the enclosing vector-domain reset chain. All other controls are local.
    // External clock-alive/stream-valid gates remain mandatory: this domain
    // cannot observe an invalidate request while its own clock has stopped.
    always @(posedge clk_vec or posedge reset) begin
        if (reset) begin
            valid <= 0; parity <= 0; failed <= 0; good_vectors <= 0;
            have_previous <= 0;
            for (p = 0; p < 2; p = p + 1) begin
                previous_a[p] <= 0; previous_b[p] <= 0;
                count[p] <= 0; coverage[p] <= 0;
            end
        end else if (invalidate || restart) begin
            valid <= 0; parity <= 0; failed <= invalidate; good_vectors <= 0;
            have_previous <= 0;
            for (p = 0; p < 2; p = p + 1) begin
                previous_a[p] <= 0; previous_b[p] <= 0;
                count[p] <= 0; coverage[p] <= 0;
            end
        end else if (!enable) begin
            // Normal mode retains the identified channel parity. Never compare
            // across an unobserved interval; an unfinished acquisition resets.
            have_previous <= 0;
            if (!valid) begin
                good_vectors <= 0;
                for (p = 0; p < 2; p = p + 1) begin count[p] <= 0; coverage[p] <= 0; end
            end
        end else if (!failed) begin
            for (p = 0; p < 2; p = p + 1) begin
                previous_a[p] <= last_a[p]; previous_b[p] <= last_b[p];
                have_previous[p] <= intra_ok[p];
                count[p] <= next_count[p]; coverage[p] <= next_coverage[p];
            end
            if (valid) begin
                // Fail closed also in simulation if a checked bit is X/Z.
                if (stream_ok[parity]) begin good_vectors <= REQUIRED_VECTORS; end
                else begin valid <= 0; failed <= 1; good_vectors <= 0; end
            end else begin
                good_vectors <= (next_count[0] >= next_count[1]) ? next_count[0] : next_count[1];
                case (qualifies)
                    2'b01: begin valid <= 1; parity <= 0; end
                    2'b10: begin valid <= 1; parity <= 1; end
                    2'b11: begin valid <= 0; failed <= 1; good_vectors <= 0; end
                    default: valid <= 0;
                endcase
            end
        end
    end
endmodule
