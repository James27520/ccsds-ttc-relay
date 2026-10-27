`timescale 1ns/1ps
module tb_pn9_train;
    reg clk_vec=0, clk_run=1;
    always #16 if (clk_run) clk_vec=~clk_vec;
    reg reset=1, restart=0, enable=0, invalidate=0;
    reg [111:0] words=0;
    wire valid, parity, failed;
    wire [15:0] good_vectors;
    tc_pn9_train dut(.*);
    reg [111:0] synthetic [0:4095];
    reg [111:0] actual0 [0:4095];
    reg [111:0] actual1 [0:4095];
    reg [111:0] actual2 [0:4095];
    reg [27:0] recurrence [0:510];
    integer checks=0, scenarios=0;
    integer i,j;
    reg [111:0] corrupt;

    task check(input logic condition,input string message);
        begin
            checks=checks+1;
            if(condition !== 1'b1) begin
                $display("FAIL PN9 t=%0t %s valid=%b parity=%b failed=%b count=%0d",$time,message,valid,parity,failed,good_vectors);
                $fatal(1,"PN9 assertion failed");
            end
        end
    endtask
    function [111:0] swapped(input [111:0] value);
        integer k;
        begin
            for(k=0;k<4;k=k+1) begin
                swapped[28*k+:14]=value[28*k+14+:14];
                swapped[28*k+14+:14]=value[28*k+:14];
            end
        end
    endfunction
    task start_training;
        begin
            scenarios=scenarios+1;
            @(negedge clk_vec);restart=1;invalidate=0;enable=1;
            @(posedge clk_vec);#1;check(!valid && !failed && good_vectors==0,"restart clears all training state");
        end
    endtask
    task feed(input [111:0] value);
        begin
            // Call immediately after a prior edge or task; never race the DUT.
            @(negedge clk_vec);restart=0;words=value;
            @(posedge clk_vec);#1;
        end
    endtask
    task lock_synthetic(input logic wanted_parity,input integer first);
        integer n;
        begin
            start_training();
            for(n=0;n<128;n=n+1)begin
                feed(wanted_parity ? swapped(synthetic[first+n]) : synthetic[first+n]);
                check(!failed,"clean acquisition cannot fail");
                check(valid==(n==127),"exactly 128 contiguous vectors required");
                check(good_vectors==n+1,"acquisition vector count");
            end
            check(valid && parity==wanted_parity && good_vectors==128,"unique parity acquired");
        end
    endtask
    task check_sticky_failure;
        integer n;
        begin
            check(!valid && failed && good_vectors==0,"locked bad stream invalidates immediately");
            for(n=0;n<160;n=n+1)begin
                feed(synthetic[700+n]);
                check(!valid && failed,"failure cannot silently reacquire");
            end
        end
    endtask

    initial begin
        $readmemh("../pn9_fixtures/pn9_synthetic.mem",synthetic);
        $readmemh("../pn9_fixtures/pn9_real_00.mem",actual0);
        $readmemh("../pn9_fixtures/pn9_real_01.mem",actual1);
        $readmemh("../pn9_fixtures/pn9_real_02.mem",actual2);
        $readmemh("../pn9_fixtures/pn9_recurrence.mem",recurrence);
        #1;check(!valid && !failed,"reset defaults invalid");
        @(negedge clk_vec);reset=0;
        for(i=0;i<511;i=i+1)
            check(dut.pn9_next(recurrence[i][27:14])===recurrence[i][13:0],"all nonzero states match independent ADI equations");

        // Every vector of each actual captured stream, not just the lock window.
        for(j=0;j<3;j=j+1)begin
            start_training();
            for(i=0;i<4096;i=i+1)begin
                case(j) 0:feed(actual0[i]);1:feed(actual1[i]);2:feed(actual2[i]);endcase
                check(!failed && valid==(i>=127),"actual captured PN9 stream lock/continuity");
                check(good_vectors==((i<128)?i+1:128),"actual capture count saturation");
                if(i>=127)check(parity==0,"actual capture parity zero");
            end
        end
        // Different PN phases and both possible interleave parities.
        for(j=0;j<4;j=j+1)begin
            lock_synthetic(j%2,37*j);
            for(i=128;i<256;i=i+1)begin
                feed((j%2)?swapped(synthetic[37*j+i]):synthetic[37*j+i]);
                check(valid && !failed && parity==j%2,"locked synthetic continuation");
            end
        end

        lock_synthetic(0,0);corrupt=synthetic[128];corrupt[12]=~corrupt[12];feed(corrupt);check_sticky_failure();
        lock_synthetic(0,0);corrupt=synthetic[128];corrupt[14]=~corrupt[14];feed(corrupt);check_sticky_failure();
        lock_synthetic(0,0);feed(synthetic[127]);check_sticky_failure(); // repeated complete vector
        lock_synthetic(0,0);feed(synthetic[129]);check_sticky_failure(); // missing complete vector
        lock_synthetic(0,0);corrupt=synthetic[128];corrupt[28+:14]=corrupt[0+:14];feed(corrupt);check_sticky_failure();
        lock_synthetic(0,0);feed(swapped(synthetic[128]));check_sticky_failure(); // parity change
        lock_synthetic(0,0);corrupt=synthetic[128];corrupt[3]=1'bx;feed(corrupt);check_sticky_failure();

        // A single corrupted pre-lock vector must restart the consecutive window.
        start_training();
        for(i=0;i<61;i=i+1)begin
            corrupt=synthetic[i];if(i==60)corrupt[12]=~corrupt[12];feed(corrupt);
            check(!valid && !failed,"pre-lock errors do not grant validity");
        end
        for(i=61;i<=188;i=i+1)begin
            feed(synthetic[i]);check(valid==(i==188),"bad vector resets the entire candidate window");
        end

        // Wrong PN polarity, zero PN state, checkerboard on both channels,
        // reversed sample order, and B stuck at a legal checker code all reject.
        for(j=0;j<5;j=j+1)begin
            start_training();
            for(i=0;i<256;i=i+1)begin
                corrupt=synthetic[i];
                case(j)
                    0:for(integer k=0;k<4;k=k+1)corrupt[28*k+:14]=corrupt[28*k+:14]^14'h3fff;
                    1:for(integer k=0;k<4;k=k+1)corrupt[28*k+:14]=14'h3fff;
                    2:for(integer k=0;k<4;k=k+1)corrupt[28*k+:14]=corrupt[28*k+14+:14];
                    3:for(integer k=0;k<4;k=k+1)corrupt[28*k+:28]=synthetic[i][28*(3-k)+:28];
                    4:for(integer k=0;k<4;k=k+1)corrupt[28*k+14+:14]=14'h1555;
                endcase
                feed(corrupt);check(!valid,"incorrect stream cannot train");
            end
        end

        // Normal-mode disable cannot inspect unrelated analog data or lose parity.
        lock_synthetic(1,0);
        @(negedge clk_vec);enable=0;words='x;
        repeat(20)begin @(posedge clk_vec);#1;check(valid && parity && !failed && good_vectors==128,"normal mode retains trained parity");end
        @(negedge clk_vec);enable=1;words=swapped(synthetic[500]);
        @(posedge clk_vec);#1;check(valid && !failed,"enable gap deliberately has no cross-gap PN assumption");
        feed(swapped(synthetic[501]));check(valid && !failed,"cross-vector checks resume after gap");
        feed(swapped(synthetic[503]));check(!valid && failed,"resumed cross-vector gap detected");

        start_training();
        for(i=0;i<60;i=i+1)feed(synthetic[i]);
        @(negedge clk_vec);enable=0;
        @(posedge clk_vec);#1;check(!valid && good_vectors==0,"disable resets unfinished acquisition");
        @(negedge clk_vec);enable=1;words=synthetic[1000];
        @(posedge clk_vec);#1;check(!valid && good_vectors==1,"re-enable starts fresh window");
        for(i=1001;i<1128;i=i+1)begin feed(synthetic[i]);check(valid==(i==1127),"fresh full window after disable");end

        // Invalidation has priority even when disabled or restart is asserted.
        @(negedge clk_vec);enable=0;invalidate=1;restart=1;
        @(posedge clk_vec);#1;check(!valid && failed && good_vectors==0,"invalidate wins over restart and disable");
        @(negedge clk_vec);invalidate=0;restart=0;
        repeat(3)begin @(posedge clk_vec);#1;check(!valid && failed,"failure retained while disabled");end
        lock_synthetic(0,100);
        // Actual stopped-domain asynchronous reset behavior; this is not a
        // substitute for the top-level independent clock-alive watchdog.
        @(negedge clk_vec);clk_run=0;#3;reset=1;#1;
        check(!valid && !failed && good_vectors==0,"reset clears lock with stopped vector clock");
        #40;clk_run=1;@(negedge clk_vec);reset=0;enable=0;
        $display("PASS PN9 training: %0d assertions, %0d acquisitions, 3 real captures, synthetic fault/mode tests",checks,scenarios);
        $finish;
    end
    initial begin #10000000;$fatal(1,"PN9 simulation timeout");end
endmodule
