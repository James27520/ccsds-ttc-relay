`timescale 1ns/1ps
// AD9643 dual-channel DDR at 125MSPS: 4 A + 4 B words per 31.25MHz vector.
// Raw words[14*k+:14] oldest first. Channel parity must be established by patterns.
module adc_rx8 #(parameter IDELAY_TAPS=0)(
 input dco_p,input dco_n,input [13:0] data_p,input [13:0] data_n,
 input ref200,input ctrl_reset,input capture_reset,input bitslip,
 output clkdiv,output delay_ready,output [111:0] words);
 wire dco,clkio;
 IBUFDS #(.DIFF_TERM("TRUE"),.IBUF_LOW_PWR("FALSE"),.IOSTANDARD("LVDS_25"))
  dco_input(.I(dco_p),.IB(dco_n),.O(dco));
 BUFIO serial_clock(.I(dco),.O(clkio));
 BUFR #(.BUFR_DIVIDE("4"),.SIM_DEVICE("7SERIES"))
  divided_clock(.I(dco),.O(clkdiv),.CE(1'b1),.CLR(ctrl_reset));
 (* IODELAY_GROUP="adc_rx_delay" *) IDELAYCTRL delay_controller(
  .REFCLK(ref200),.RST(ctrl_reset),.RDY(delay_ready));
 genvar lane;
 generate for(lane=0;lane<14;lane=lane+1) begin: lanes
  wire input_data,delayed;
  IBUFDS #(.DIFF_TERM("TRUE"),.IBUF_LOW_PWR("FALSE"),.IOSTANDARD("LVDS_25"))
   input_buffer(.I(data_p[lane]),.IB(data_n[lane]),.O(input_data));
  (* IODELAY_GROUP="adc_rx_delay" *) IDELAYE2 #(
   .CINVCTRL_SEL("FALSE"),.DELAY_SRC("IDATAIN"),.HIGH_PERFORMANCE_MODE("TRUE"),
   .IDELAY_TYPE("FIXED"),.IDELAY_VALUE(IDELAY_TAPS),.PIPE_SEL("FALSE"),
   .REFCLK_FREQUENCY(200.0),.SIGNAL_PATTERN("DATA")) delay_element(
   .DATAOUT(delayed),.IDATAIN(input_data),.DATAIN(1'b0),.C(clkdiv),
   .CE(1'b0),.INC(1'b0),.LD(1'b0),.LDPIPEEN(1'b0),.REGRST(1'b0),
   .CNTVALUEIN(5'b0),.CNTVALUEOUT(),.CINVCTRL(1'b0));
  ISERDESE2 #(.DATA_RATE("DDR"),.DATA_WIDTH(8),.INTERFACE_TYPE("NETWORKING"),
   .IOBDELAY("IFD"),.NUM_CE(1),.SERDES_MODE("MASTER")) deserializer(
   .D(1'b0),.DDLY(delayed),.CLK(clkio),.CLKB(!clkio),.CLKDIV(clkdiv),.CLKDIVP(1'b0),
   .OCLK(1'b0),.OCLKB(1'b0),.CE1(1'b1),.CE2(1'b1),.RST(capture_reset),.BITSLIP(bitslip),
   .DYNCLKDIVSEL(1'b0),.DYNCLKSEL(1'b0),.OFB(1'b0),.SHIFTIN1(1'b0),.SHIFTIN2(1'b0),
   .O(),.SHIFTOUT1(),.SHIFTOUT2(),
   .Q8(words[lane]),.Q7(words[14+lane]),.Q6(words[28+lane]),.Q5(words[42+lane]),
   .Q4(words[56+lane]),.Q3(words[70+lane]),.Q2(words[84+lane]),.Q1(words[98+lane]));
 end endgenerate
endmodule
