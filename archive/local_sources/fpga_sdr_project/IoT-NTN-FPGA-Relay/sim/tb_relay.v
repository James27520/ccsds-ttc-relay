`timescale 1ns / 1ps
//=============================================================================
// tb_relay.v -- functional testbench for the bent-pipe relay datapath
//
//   dq_data_clk = 30.72 MHz (data domain)
//   raxi_clk    = 100 MHz    (separate domain, so the CDC is really exercised)
//
//   Stimulus : complex tone at +fs_ch/64 from a 64-entry LUT, amplitude 2000.
//              fs_ch is the per-channel sample rate:
//                1R1T : fs_ch = dq_data_clk        = 30.72 MHz
//                2R2T : fs_ch = dq_data_clk / 4    =  7.68 MHz
//              Frequency words are power-of-two fractions of 2^32, so the
//              output tone always lands exactly on an FFT bin.
//
//   Dumps (analysed by analyse_relay.py):
//      fd  -> <name>.txt   : relayed channel 1
//      fd2 -> <name>_ch2.txt: relayed channel 2
//=============================================================================
module tb_relay;

    //------------------------------------------------------------------
    // clocks / reset
    //------------------------------------------------------------------
    reg dclk = 1'b0;
    reg aclk = 1'b0;
    reg rst_n = 1'b0;

    always #16.276 dclk = ~dclk;    // ~30.72 MHz
    always #5.0    aclk = ~aclk;    // 100 MHz

    //------------------------------------------------------------------
    // DUT
    //------------------------------------------------------------------
    reg  signed [11:0] adc_i  = 12'sd0;
    reg  signed [11:0] adc_q  = 12'sd0;
    reg               adc_v   = 1'b0;
    reg  signed [11:0] adc2_i = 12'sd0;
    reg  signed [11:0] adc2_q = 12'sd0;
    reg               adc2_v  = 1'b0;

    reg        phy_mode = 1'b1;     // 1R1T

    reg [1:0]  c_mode     = 2'd0;
    reg        c_dc_en    = 1'b0;
    reg [11:0] c_gain     = 12'h800;
    reg [31:0] c_ddc_freq = 32'd0;
    reg [31:0] c_duc_freq = 32'd0;

    wire        dac_v;
    wire [11:0] dac_d1, dac_q1, dac_d2, dac_q2;
    wire [31:0] st_sample, st_clip, st_out;

    relay_dq #(.SNAP_PERIOD(64)) dut (
        .dq_data_clk   (dclk),
        .rst_n         (rst_n),
        .adc_d1q1_valid(adc_v),
        .adc_data_d1   (adc_i),
        .adc_data_q1   (adc_q),
        .adc_d2q2_valid(adc2_v),
        .adc_data_d2   (adc2_i),
        .adc_data_q2   (adc2_q),
        .dac_valid     (dac_v),
        .dac_data_d1   (dac_d1),
        .dac_data_q1   (dac_q1),
        .dac_data_d2   (dac_d2),
        .dac_data_q2   (dac_q2),
        .phy_mode      (phy_mode),
        .raxi_clk      (aclk),
        .ctrl_mode     (c_mode),
        .ctrl_dc_en    (c_dc_en),
        .ctrl_gain     (c_gain),
        .ctrl_ddc_freq (c_ddc_freq),
        .ctrl_duc_freq (c_duc_freq),
        .status_sample_cnt (st_sample),
        .status_clip_cnt   (st_clip),
        .status_out_cnt    (st_out)
    );

    //------------------------------------------------------------------
    // tone LUT : 64 samples per period
    //------------------------------------------------------------------
    reg signed [11:0] tone_i [0:63];
    reg signed [11:0] tone_q [0:63];

    function signed [11:0] q12r;
        input real v;
        integer t;
        begin
            t = $rtoi(v);
            if ((v >= 0.0) && ((v - t) >= 0.5)) t = t + 1;
            if ((v <  0.0) && ((t - v) >= 0.5)) t = t - 1;
            if (t >  2047) t =  2047;
            if (t < -2048) t = -2048;
            q12r = t[11:0];
        end
    endfunction

    real    twopi;
    integer k;

    //------------------------------------------------------------------
    // stimulus generator
    //   1R1T : adc_v high every data_clk
    //   2R2T : adc_v high on group phase 1, adc2_v high on phase 3
    //          (exactly how phy_rx drives the two channels)
    //------------------------------------------------------------------
    reg       stim_en  = 1'b0;
    reg       stim_dc  = 1'b0;
    reg       stim_r2t = 1'b0;
    reg [5:0] ph1      = 6'd0;
    reg [5:0] ph2      = 6'd0;
    reg [1:0] grp      = 2'd0;

    always @(posedge dclk) begin
        if (!rst_n) begin
            adc_v  <= 1'b0;
            adc2_v <= 1'b0;
            adc_i  <= 12'sd0;
            adc_q  <= 12'sd0;
            adc2_i <= 12'sd0;
            adc2_q <= 12'sd0;
            ph1    <= 6'd0;
            ph2    <= 6'd0;
            grp    <= 2'd0;
        end else if (stim_en) begin
            grp <= grp + 2'd1;
            if (stim_r2t) begin
                adc_v  <= (grp == 2'd1);
                adc2_v <= (grp == 2'd3);
                if (grp == 2'd1) begin
                    adc_i <= tone_i[ph1];
                    adc_q <= tone_q[ph1];
                    ph1   <= ph1 + 6'd1;
                end
                if (grp == 2'd3) begin
                    adc2_i <= tone_i[ph2];
                    adc2_q <= tone_q[ph2];
                    ph2    <= ph2 + 6'd1;
                end
            end else begin
                adc_v  <= 1'b1;
                adc2_v <= 1'b0;
                if (stim_dc) begin
                    adc_i <= 12'sd2047;
                    adc_q <= 12'sd0;
                end else begin
                    adc_i <= tone_i[ph1];
                    adc_q <= tone_q[ph1];
                    ph1   <= ph1 + 6'd1;
                end
            end
        end else begin
            adc_v  <= 1'b0;
            adc2_v <= 1'b0;
        end
    end

    //------------------------------------------------------------------
    // output capture (negedge: all NBA updates have settled)
    //------------------------------------------------------------------
    integer fd;
    integer fd2;
    reg     dump_en = 1'b0;

    always @(negedge dclk) begin
        if (dump_en && dac_v) begin
            $fwrite(fd,  "%0d %0d\n", $signed(dac_d1), $signed(dac_q1));
            $fwrite(fd2, "%0d %0d\n", $signed(dac_d2), $signed(dac_q2));
        end
    end

    //------------------------------------------------------------------
    // helpers
    //------------------------------------------------------------------
    task settle_ctrl;
        integer j;
        begin
            for (j = 0; j < 40; j = j + 1) @(posedge dclk);
        end
    endtask

    task run_test;
        input [1023:0] fname;
        input integer  nsamp;
        input          dc_mode;
        input          r2t;
        begin
            if (fd  != 0) $fclose(fd);
            if (fd2 != 0) $fclose(fd2);
            fd  = $fopen(fname, "w");
            fd2 = $fopen({fname, "_ch2.txt"}, "w");
            c_dc_en  <= 1'b0;
            stim_dc  <= dc_mode;
            stim_r2t <= r2t;
            ph1      = 6'd0;
            ph2      = 6'd0;
            grp      = 2'd0;
            stim_en  <= 1'b1;
            dump_en  <= 1'b1;
            for (k = 0; k < nsamp; k = k + 1) @(negedge dclk);
            dump_en <= 1'b0;
            stim_en <= 1'b0;
            for (k = 0; k < 8; k = k + 1) @(negedge dclk);
            if (fd  != 0) $fclose(fd);
            if (fd2 != 0) $fclose(fd2);
            $display("  wrote %0s", fname);
        end
    endtask

    //------------------------------------------------------------------
    // main sequence
    //------------------------------------------------------------------
    initial begin
        twopi = 2.0 * 3.14159265358979323846;
        fd    = 0;
        fd2   = 0;

        for (k = 0; k < 64; k = k + 1) begin
            tone_i[k] = q12r(2000.0 * $cos(twopi * k / 64.0));
            tone_q[k] = q12r(2000.0 * $sin(twopi * k / 64.0));
        end

        $display("=== tb_relay start ===");

        rst_n = 1'b0;
        repeat (20) @(posedge dclk);
        rst_n = 1'b1;
        repeat (10) @(posedge dclk);

        // ---- T1 : NCO phasor, DC input, DUC only, unity gain ----
        $display("T1 nco.txt");
        c_mode     <= 2'd3;
        c_gain     <= 12'h800;
        c_ddc_freq <= 32'h04000000;
        c_duc_freq <= 32'h04000000;
        settle_ctrl();
        run_test("nco.txt", 400, 1'b1, 1'b0);

        // ---- T2 : BYPASS ----
        $display("T2 bypass.txt");
        c_mode     <= 2'd0;
        c_ddc_freq <= 32'd0;
        c_duc_freq <= 32'd0;
        settle_ctrl();
        run_test("bypass.txt", 512, 1'b0, 1'b0);

        // ---- T3 : RELAY, ddc == duc -> net 0 ----
        $display("T3 relay_netzero.txt");
        c_mode     <= 2'd1;
        c_ddc_freq <= 32'h04000000;
        c_duc_freq <= 32'h04000000;
        settle_ctrl();
        run_test("relay_netzero.txt", 512, 1'b0, 1'b0);

        // ---- T4 : DUC_ONLY +fs/64 -> tone moves to fs/32 ----
        $display("T4 duc_only.txt");
        c_mode     <= 2'd3;
        c_ddc_freq <= 32'd0;
        c_duc_freq <= 32'h04000000;
        settle_ctrl();
        run_test("duc_only.txt", 512, 1'b0, 1'b0);

        // ---- T5 : RELAY ddc=+fs/64 duc=0 -> net -fs/64 -> DC ----
        $display("T5 relay_minus.txt");
        c_mode     <= 2'd1;
        c_ddc_freq <= 32'h04000000;
        c_duc_freq <= 32'd0;
        settle_ctrl();
        run_test("relay_minus.txt", 512, 1'b0, 1'b0);

        // ---- T6 : MUTE ----
        $display("T6 mute.txt");
        c_mode <= 2'd2;
        settle_ctrl();
        run_test("mute.txt", 128, 1'b0, 1'b0);

        // ---- T7 : DUC only, freq 0, gain 0.5 ----
        $display("T7 gain_half.txt");
        c_mode     <= 2'd3;
        c_gain     <= 12'h400;
        c_ddc_freq <= 32'd0;
        c_duc_freq <= 32'd0;
        settle_ctrl();
        run_test("gain_half.txt", 256, 1'b0, 1'b0);

        // ---- T8 : overdrive -> saturation ----
        $display("T8 clip.txt");
        c_mode     <= 2'd3;
        c_gain     <= 12'hFFF;
        c_ddc_freq <= 32'd0;
        c_duc_freq <= 32'd0;
        settle_ctrl();
        run_test("clip.txt", 256, 1'b0, 1'b0);

        // ---- T9 : 2R2T sparse valid, DUC only +fs_ch/64 ----
        $display("T9 r2t_duc.txt");
        phy_mode   <= 1'b0;            // 2R2T
        c_mode     <= 2'd3;
        c_gain     <= 12'h800;
        c_ddc_freq <= 32'd0;
        c_duc_freq <= 32'h04000000;
        settle_ctrl();
        run_test("r2t_duc.txt", 1600, 1'b0, 1'b1);

        // ---- T10 : 2R2T relay, ddc == duc -> net 0 ----
        $display("T10 r2t_netzero.txt");
        c_mode     <= 2'd1;
        c_ddc_freq <= 32'h04000000;
        c_duc_freq <= 32'h04000000;
        settle_ctrl();
        run_test("r2t_netzero.txt", 1600, 1'b0, 1'b1);

        repeat (5000) @(posedge dclk);
        $display("=== counters : sample=%0d clip=%0d out=%0d ===",
                 st_sample, st_clip, st_out);
        if ((st_sample > 0) && (st_out > 0) && (st_clip > 0))
            $display("=== COUNTER CHECK : PASS ===");
        else
            $display("=== COUNTER CHECK : FAIL ===");
        $display("=== tb_relay done ===");
        $finish;
    end

endmodule
