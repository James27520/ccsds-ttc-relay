
`timescale 1 ns / 1 ps

	module axi_ctrl_v1_0 #
	(
		// Users to add parameters here
		
		// Parameters of Axi Slave Bus Interface S00_AXI
		parameter integer C_S00_AXI_DATA_WIDTH	= 32,
		parameter integer C_S00_AXI_ADDR_WIDTH	= 6
	)
	(
		// Users to add ports here
		output wire [6:0] idelay_en,
		output wire [4:0] idelay_tap,
		output wire [11:0] phase_inc,
		output wire           phy_mode,
		// ---- channel 1 ----
		output wire [1:0]   relay_mode,
		output wire [31:0]  relay_ddc_freq,
		output wire [31:0]  relay_duc_freq,
		output wire [11:0]  relay_gain,
		output wire         relay_dc_en,
		// ---- channel 2 ----
		output wire [1:0]   relay_mode2,
		output wire [31:0]  relay_ddc_freq2,
		output wire [31:0]  relay_duc_freq2,
		output wire [11:0]  relay_gain2,
		output wire         relay_dc_en2,
		// ---- status ----
		input  wire [31:0]  status_sample_cnt,
		input  wire [31:0]  status_clip_cnt,
		input  wire [31:0]  status_out_cnt,
		input  wire [31:0]  status_sample_cnt2,
		input  wire [31:0]  status_clip_cnt2,
		// User ports ends
		// Do not modify the ports beyond this line


		// Ports of Axi Slave Bus Interface S00_AXI
		input wire  s00_axi_aclk,
		input wire  s00_axi_aresetn,
		input wire [C_S00_AXI_ADDR_WIDTH-1 : 0] s00_axi_awaddr,
		input wire [2 : 0] s00_axi_awprot,
		input wire  s00_axi_awvalid,
		output wire  s00_axi_awready,
		input wire [C_S00_AXI_DATA_WIDTH-1 : 0] s00_axi_wdata,
		input wire [(C_S00_AXI_DATA_WIDTH/8)-1 : 0] s00_axi_wstrb,
		input wire  s00_axi_wvalid,
		output wire  s00_axi_wready,
		output wire [1 : 0] s00_axi_bresp,
		output wire  s00_axi_bvalid,
		input wire  s00_axi_bready,
		input wire [C_S00_AXI_ADDR_WIDTH-1 : 0] s00_axi_araddr,
		input wire [2 : 0] s00_axi_arprot,
		input wire  s00_axi_arvalid,
		output wire  s00_axi_arready,
		output wire [C_S00_AXI_DATA_WIDTH-1 : 0] s00_axi_rdata,
		output wire [1 : 0] s00_axi_rresp,
		output wire  s00_axi_rvalid,
		input wire  s00_axi_rready
	);
// Instantiation of Axi Bus Interface S00_AXI
	axi_lite_v1_0_S00_AXI # ( 
		.C_S_AXI_DATA_WIDTH(C_S00_AXI_DATA_WIDTH),
		.C_S_AXI_ADDR_WIDTH(C_S00_AXI_ADDR_WIDTH)
	) axi_lite_v1_0_S00_AXI_inst (
		.idelay_en(idelay_en),
		.idelay_tap(idelay_tap),
		.phase_inc(phase_inc),
		.phy_mode(phy_mode),
		.relay_mode(relay_mode),
		.relay_ddc_freq(relay_ddc_freq),
		.relay_duc_freq(relay_duc_freq),
		.relay_gain(relay_gain),
		.relay_dc_en(relay_dc_en),
		.relay_mode2(relay_mode2),
		.relay_ddc_freq2(relay_ddc_freq2),
		.relay_duc_freq2(relay_duc_freq2),
		.relay_gain2(relay_gain2),
		.relay_dc_en2(relay_dc_en2),
		.status_sample_cnt(status_sample_cnt),
		.status_clip_cnt(status_clip_cnt),
		.status_out_cnt(status_out_cnt),
		.status_sample_cnt2(status_sample_cnt2),
		.status_clip_cnt2(status_clip_cnt2),
		
		.S_AXI_ACLK(s00_axi_aclk),
		.S_AXI_ARESETN(s00_axi_aresetn),
		.S_AXI_AWADDR(s00_axi_awaddr),
		.S_AXI_AWPROT(s00_axi_awprot),
		.S_AXI_AWVALID(s00_axi_awvalid),
		.S_AXI_AWREADY(s00_axi_awready),
		.S_AXI_WDATA(s00_axi_wdata),
		.S_AXI_WSTRB(s00_axi_wstrb),
		.S_AXI_WVALID(s00_axi_wvalid),
		.S_AXI_WREADY(s00_axi_wready),
		.S_AXI_BRESP(s00_axi_bresp),
		.S_AXI_BVALID(s00_axi_bvalid),
		.S_AXI_BREADY(s00_axi_bready),
		.S_AXI_ARADDR(s00_axi_araddr),
		.S_AXI_ARPROT(s00_axi_arprot),
		.S_AXI_ARVALID(s00_axi_arvalid),
		.S_AXI_ARREADY(s00_axi_arready),
		.S_AXI_RDATA(s00_axi_rdata),
		.S_AXI_RRESP(s00_axi_rresp),
		.S_AXI_RVALID(s00_axi_rvalid),
		.S_AXI_RREADY(s00_axi_rready)
	);

	endmodule
