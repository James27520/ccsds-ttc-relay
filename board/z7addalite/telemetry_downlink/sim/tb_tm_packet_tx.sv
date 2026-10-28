`timescale 1ns/1ps
module tb_tm_packet_tx;
 localparam integer SC=2500;
 reg clk25=0,dac_clk=0;
 always #20 clk25=~clk25;
 always #2 dac_clk=~dac_clk;
 reg reset25=1,dac_reset=1,config_verified=0,wr_en=0;
 reg [31:0] wr_addr=0,wr_data=0,rd_addr=32'h43c01000;
 reg [3:0] wr_strb=15;
 wire wr_error,rd_error,tx_active,tx_bit,tx_symbol_start;
 wire signed [15:0] dac_sample;
 wire [31:0] rd_data;
 integer checks=0,packets=0,cycle_checks=0;
 tm_packet_tx #(.SYMBOL_CYCLES(SC)) dut(.*);
 task check(input bit okay,input string label_text);
  begin checks++;if(!okay)$fatal(1,"FAIL %s at %t",label_text,$time);end
 endtask
 task write_reg(input integer off,input [31:0] value,input [3:0] strb,input bit expect_error);
  begin
   @(negedge clk25);wr_addr=32'h43c01000+off;wr_data=value;wr_strb=strb;wr_en=1;
   #1;check(wr_error===expect_error,$sformatf("write +%h error=%b",off,expect_error));
   @(negedge clk25);wr_en=0;
  end
 endtask
 task read_check(input integer off,input [31:0] mask,input [31:0] expected);
  begin rd_addr=32'h43c01000+off;#1;check(!rd_error && ((rd_data&mask)==expected),$sformatf("read +%h got %h",off,rd_data));end
 endtask
 task send_then_stop;
  begin
   @(negedge clk25);wr_addr=32'h43c01014;wr_data=1;wr_strb=15;wr_en=1;
   #1;check(!wr_error,"back-to-back SEND accepted");
   @(negedge clk25);wr_addr=32'h43c01018;
   #1;check(!wr_error,"back-to-back STOP accepted while command crossing");
   @(negedge clk25);wr_en=0;
  end
 endtask
 task idle_zero(input integer clocks);
  begin repeat(clocks)begin @(negedge dac_clk);check(dac_sample===16'sd0 && !tx_active,"idle strict zero");end end
 endtask
 task wait_done;
  integer timeout_cycles;
  begin
   timeout_cycles=0;rd_addr=32'h43c01000;#1;
   while(rd_data[0] && timeout_cycles<1000)begin @(negedge clk25);timeout_cycles++;end
   check(!rd_data[0] && rd_data[3],$sformatf("completion releases owner status=%h timeout=%0d",rd_data,timeout_cycles));
  end
 endtask
 task reset_both;
  begin
   reset25=1;dac_reset=1;#1;check(dac_sample===16'sd0,"reset gates sample immediately");
   read_check(0,128,128);
   write_reg('h0c,32'hdeadbeef,15,1);write_reg('h10,32,15,1);
   write_reg('h08,1,15,1);write_reg('h14,1,15,1);write_reg('h18,1,15,1);
   repeat(5)@(negedge clk25);reset25=0;dac_reset=0;
   repeat(6)@(negedge clk25);
   read_check(0,192,0);
  end
 endtask
 // Independent phase and sine model checks every physical DAC sample, as well
 // as every bit and every 2500-clock symbol. MSB-first spans three RAM words.
 task observe_packet(input [95:0] bits_msb,input integer nbits);
  integer k,bitidx,expected_sample,magnitude;
  reg [31:0] phase_model;
  real v;
  begin
   wait(tx_active);#0.1;phase_model=0;k=0;
   while(tx_active)begin
    bitidx=k/SC;
    check(bitidx<nbits,"packet does not overrun length");
    check(tx_bit===bits_msb[95-bitidx],$sformatf("MSB bit %0d",bitidx));
    check(tx_symbol_start==((k%SC)==0),"symbol pulse width and spacing");
    if(k==0)expected_sample=0;
    else begin
     v=128.0*$sin(6.283185307179586*(phase_model[31:26])/64.0);
     magnitude=(v>=0)?$rtoi(v+0.5):$rtoi(v-0.5);
     expected_sample=bits_msb[95-bitidx]?magnitude:-magnitude;
     phase_model=phase_model+32'd1554778161;
    end
    check($signed(dac_sample)==expected_sample,$sformatf("DDS/BPSK sample cycle=%0d got=%0d want=%0d",k,$signed(dac_sample),expected_sample));
    check($signed(dac_sample)<=128 && $signed(dac_sample)>=-128,"fixed amplitude bound");
    cycle_checks++;k++;
    @(posedge dac_clk);#0.1;
   end
   check(k==nbits*SC,$sformatf("exact packet cycles %0d",k));
   packets++;idle_zero(10);
  end
 endtask
 reg [95:0] pattern=96'h9635a7c18012fed980000000;
 integer i;
 initial begin
  reset_both();idle_zero(10);
  read_check('h1c,32'hffffffff,32'h544d5431);read_check('h20,32'hffffffff,1);
  write_reg('h14,1,15,1); // empty or not ready
  write_reg('h08,1,15,0);
  write_reg('h0c,32'hdeadbeef,3,1);read_check('h28,32'hffffffff,0);
  write_reg('h10,0,15,1);write_reg('h10,4097,15,1);
  write_reg('h10,1,15,1);write_reg('h30,1,15,1);write_reg('h0d,1,15,1);
  rd_addr=32'h43c02000;#1;check(rd_error,"out of aperture read rejected");
  @(negedge clk25);wr_addr=32'h43c0200c;wr_en=1;wr_data=0;#1;check(wr_error,"out of aperture write rejected");
  @(negedge clk25);wr_en=0;
  write_reg('h08,1,15,0);
  write_reg('h0c,pattern[95:64],15,0);write_reg('h10,32,15,0);
  write_reg('h14,1,15,1); // config not verified
  config_verified=1;repeat(6)@(negedge clk25);
  write_reg('h08,1,15,0);
  write_reg('h0c,pattern[95:64],15,0);write_reg('h0c,pattern[63:32],15,0);write_reg('h0c,pattern[31:0],15,0);
  write_reg('h10,65,15,0);read_check('h24,32'hffffffff,65);read_check('h28,32'hffffffff,3);
  fork
   observe_packet(pattern,65);
   begin
    write_reg('h14,1,15,0);
    write_reg('h0c,0,15,1);write_reg('h10,1,15,1);write_reg('h08,1,15,1);write_reg('h14,1,15,1);
   end
  join
  wait_done();read_check('h04,4,4);write_reg('h14,1,15,1);idle_zero(100);
  // One-bit final packet must produce exactly one symbol then strict zero.
  write_reg('h08,1,15,0);write_reg('h0c,32'h80000000,15,0);write_reg('h10,1,15,0);
  fork observe_packet(96'h800000000000000000000000,1);write_reg('h14,1,15,0);join
  wait_done();idle_zero(10);
  // Capacity and malformed command checks.
  write_reg('h08,1,15,0);
  for(i=0;i<128;i++)write_reg('h0c,i,15,0);
  write_reg('h0c,0,15,1);write_reg('h10,4096,15,0);read_check('h28,32'hffffffff,128);
  write_reg('h18,0,15,1);write_reg('h08,1,15,0);
  // STOP while a command is still crossing the mailbox must release owner.
  write_reg('h0c,32'h12345678,15,0);write_reg('h10,32,15,0);
  send_then_stop();read_check(0,64,64);wait_done();read_check(0,65,64);idle_zero(50);
  repeat(6)@(negedge clk25);read_check(0,192,0);
  read_check('h04,64,64);write_reg('h14,1,15,1);
  // STOP during a running symbol, then rearming config cannot resume it.
  write_reg('h08,1,15,0);write_reg('h0c,32'hffffffff,15,0);write_reg('h10,32,15,0);
  write_reg('h14,1,15,0);wait(tx_active);repeat(40)@(negedge dac_clk);
  write_reg('h18,1,15,0);wait_done();idle_zero(40);
  config_verified=0;repeat(10)@(negedge dac_clk);config_verified=1;idle_zero(40);
  write_reg('h14,1,15,1);
  // Config falling gates output immediately and aborts permanently.
  write_reg('h08,1,15,0);write_reg('h0c,32'hffffffff,15,0);write_reg('h10,32,15,0);
  write_reg('h14,1,15,0);wait(tx_active);repeat(40)@(negedge dac_clk);
  #0.7;config_verified=0;#0.1;check(dac_sample===16'sd0,"config loss immediate gate");
  repeat(5)@(negedge dac_clk);config_verified=1;wait_done();idle_zero(40);
  read_check('h04,128,128);write_reg('h14,1,15,1);
  // Both domain resets discard in-flight work and never send by themselves.
  write_reg('h08,1,15,0);write_reg('h0c,32'hffffffff,15,0);write_reg('h10,32,15,0);
  write_reg('h14,1,15,0);wait(tx_active);repeat(40)@(negedge dac_clk);reset_both();idle_zero(100);
  read_check(0,32'h3f,2);read_check('h28,32'hffffffff,0);
  // A post-reset packet checks that no stale command/completion survives.
  write_reg('h0c,32'h00000000,15,0);write_reg('h10,2,15,0);
  fork observe_packet(96'd0,2);write_reg('h14,1,15,0);join
  wait_done();idle_zero(40);
  $display("PASS checks=%0d full_packets=%0d sample_cycles=%0d SYMBOL_CYCLES=%0d",checks,packets,cycle_checks,SC);
  $finish;
 end
 initial begin #5000000;$fatal(1,"global timeout");end
endmodule
