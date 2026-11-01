`timescale 1ns/1ps
module tb_nco_axis;
  reg clk=0, rst_n=0, enable=0;
  reg [31:0] word=0;
  always #5 clk=~clk;
  wire signed [11:0] c,s;
  relay_nco nco(clk,rst_n,enable,word,c,s);
  reg valid=0, check_path=0;
  reg signed [11:0] xi=0,xq=0;
  wire ov, clip;
  wire signed [11:0] yi,yq;
  relay_path path(.clk(clk),.rst_n(rst_n),.mode(2'd1),.dc_en(1'b0),
    .gain_word(12'h800),.ddc_cos(c),.ddc_sin(s),.duc_cos(c),.duc_sin(s),
    .in_valid(valid),.in_i(xi),.in_q(xq),.out_valid(ov),
    .out_i(yi),.out_q(yq),.clip_flag(clip));
  integer clips=0, checked=0, k,j;
  reg [8:0] qv=0;
  integer qi[0:8],qq[0:8];
  function integer unity2(input integer v);
    integer a;
    begin a=(v*2047)>>>11; unity2=(a*2047)>>>11; end
  endfunction
  always @(posedge clk) begin
    if (!rst_n) begin
      qv=0;
      for(integer d=0;d<9;d=d+1) begin qi[d]=0;qq[d]=0;end
    end else if(check_path) begin
      for(integer d=8;d>0;d=d-1) begin qi[d]=qi[d-1];qq[d]=qq[d-1];end
      qi[0]=unity2($signed(xi));qq[0]=unity2($signed(xq));
      qv={qv[7:0],valid};
      #1;
      if(ov!==qv[8]) $fatal(1,"valid latency mismatch");
      if(ov) begin
        checked=checked+1;
        if(clip) clips=clips+1;
`ifndef BASELINE
        if(clip || $signed(yi)!=qi[8] || $signed(yq)!=qq[8])
          $fatal(1,"zero-shift path mismatch got %0d,%0d clip=%0b expected %0d,%0d",yi,yq,clip,qi[8],qq[8]);
`endif
      end
    end
  end
  reg [31:0] phase=0, delayed=0, effective;
  integer ec,es;
  function integer sine(input integer ph);
    integer off,amp;
    real a;
    begin
      off=ph%1024;
      if(off==0) begin
        case(ph/1024) 0:sine=0;1:sine=2047;2:sine=0;3:sine=-2047;endcase
      end else begin
        a=6.283185307179586*(ph+0.5)/4096.0;
        amp=$rtoi(2047.0*$sin(a)+( $sin(a)>=0.0 ? 0.5 : -0.5));
        sine=amp;
      end
    end
  endfunction
  task tick_nco(input reg en,input reg [31:0] fw);
    begin
      @(negedge clk);enable=en;word=fw;
      effective=en ? phase+fw : phase;
      @(posedge clk); #2;
      es=sine(delayed[31:20]);
      ec=sine((delayed[31:20]+1024)%4096);
      if($signed(c)!=ec || $signed(s)!=es)
        $fatal(1,"NCO mismatch phase=%h got %0d,%0d expected %0d,%0d",delayed,c,s,ec,es);
      delayed=effective;phase=effective;
    end
  endtask
  initial begin
    for(j=0;j<9;j=j+1) begin qi[j]=0;qq[j]=0;end
    repeat(5) @(negedge clk);rst_n=1;enable=1;
    repeat(10) @(negedge clk);
    check_path=1;
    // Every code on either component, all four extreme corners, and
    // 1-in-4 valid pacing exercise the zero-shift pipeline end to end.
    for(k=-2048;k<2048;k=k+1) begin
      @(negedge clk);valid=1;xi=k;xq=(k&1)?2047:-2048;
      repeat(3) begin @(negedge clk);valid=0;end
      @(negedge clk);valid=1;xi=(k&1)?2047:-2048;xq=k;
      repeat(3) begin @(negedge clk);valid=0;end
    end
    @(negedge clk);valid=0;
    repeat(12) @(negedge clk);
    check_path=0;
`ifdef BASELINE
    if(clips==0) $fatal(1,"baseline did not reproduce the clipping corner");
    $display("BASELINE_REPRODUCED checked=%0d clips=%0d cos=%0d sin=%0d",checked,clips,c,s);
`else
    if(checked!=8192 || clips!=0) $fatal(1,"coverage or clipping mismatch");
    // Reset before verifying absolute phase, latency, valid gaps and
    // both signs of frequency. Zero word continues to HOLD phase.
    @(negedge clk);rst_n=0;enable=0;word=0;
    repeat(4) @(negedge clk);rst_n=1;
    repeat(4) @(negedge clk);
    for(k=0;k<16;k=k+1) tick_nco(1,32'h40000000);
    for(k=0;k<40;k=k+1) tick_nco(k%3!=0,32'h01712345);
    for(k=0;k<20;k=k+1) tick_nco(0,32'h01712345);
    for(k=0;k<40;k=k+1) tick_nco(k%4!=0,32'hfe543211);
    for(k=0;k<10;k=k+1) tick_nco(1,32'h00000000);
    $display("CANDIDATE_PASS checked=%0d clips=%0d",checked,clips);
`endif
    $finish;
  end
  initial begin #1000000;$fatal(1,"test timeout");end
endmodule
