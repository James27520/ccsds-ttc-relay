module telecontrol_top(
 input clk50m,input rst_n,output enable_fan,
 output clk_sda,output clk_sclk,output clk_cs,output clk_rstn,output clk_refsel,output clk_sync,
 inout adc_sda,output adc_sclk,output adc_cs,
 output dac_sda,output dac_sclk,output dac_cs,output dac_rstn,
 input adc_dco_p,input adc_dco_n,input [13:0] adc_data_p,input [13:0] adc_data_n,
 output dac_frame_p,output dac_frame_n,output dac_dci_p,output dac_dci_n,
 output [15:0] dac_data_p,output [15:0] dac_data_n,
 inout [14:0] DDR_addr,
 inout [2:0] DDR_ba,
 inout DDR_cas_n,
 inout DDR_ck_n,
 inout DDR_ck_p,
 inout DDR_cke,
 inout DDR_cs_n,
 inout [3:0] DDR_dm,
 inout [31:0] DDR_dq,
 inout [3:0] DDR_dqs_n,
 inout [3:0] DDR_dqs_p,
 inout DDR_odt,
 inout DDR_ras_n,
 inout DDR_reset_n,
 inout DDR_we_n,
 inout FIXED_IO_ddr_vrn,
 inout FIXED_IO_ddr_vrp,
 inout [53:0] FIXED_IO_mio,
 inout FIXED_IO_ps_clk,
 inout FIXED_IO_ps_porb,
 inout FIXED_IO_ps_srstb);
 wire clk25,clk200,locked,ps_resetn;
 clk_wiz_tc clock_gen(.clk_in1(clk50m),.resetn(rst_n),.clk_out1(clk25),.clk_out2(clk200),.locked(locked));
 wire reset_async=!rst_n || !locked;
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] reset25_sync=7,reset200_sync=7,ps_reset_sync=7;
 always @(posedge clk25 or posedge reset_async)if(reset_async)reset25_sync<=7;else reset25_sync<={reset25_sync[1:0],1'b0};
 always @(posedge clk200 or posedge reset_async)if(reset_async)reset200_sync<=7;else reset200_sync<={reset200_sync[1:0],1'b0};
 wire ps_reset_async=reset_async || !ps_resetn;
 always @(posedge clk25 or posedge ps_reset_async)if(ps_reset_async)ps_reset_sync<=7;else ps_reset_sync<={ps_reset_sync[1:0],1'b0};
 wire reset25=reset25_sync[2],reset200=reset200_sync[2];
 // One capture-subsystem reset reaches BOTH FIFO/mailbox domains. ADC framing
 // remains continuous during PS restart and runtime mode changes.
 wire capture_reset25=reset25 || ps_reset_sync[2];
 wire axi_resetn=!capture_reset25;
 assign enable_fan=1;assign clk_rstn=rst_n;assign clk_refsel=0;assign clk_sync=1;
 assign dac_rstn=0;assign dac_sda=0;assign dac_sclk=0;assign dac_cs=1;
 OBUFDS #(.IOSTANDARD("LVDS_25")) frame_out(.I(1'b0),.O(dac_frame_p),.OB(dac_frame_n));
 OBUFDS #(.IOSTANDARD("LVDS_25")) dci_out(.I(1'b0),.O(dac_dci_p),.OB(dac_dci_n));
 genvar n;generate for(n=0;n<16;n=n+1)begin:dac_static
  OBUFDS #(.IOSTANDARD("LVDS_25")) data_out(.I(1'b0),.O(dac_data_p[n]),.OB(dac_data_n[n]));
 end endgenerate
 wire mode_start,mode_value,startup_finished,config_busy,config_verified,adc_sdo,adc_oe,result_toggle;
 wire [31:0] active_mode,config_epoch;wire [111:0] live_diag;
 assign adc_sda=adc_oe?adc_sdo:1'bz;
 tc_adc_config adc_config(.clk25(clk25),.reset(reset25),.mode_start(mode_start),.mode_value(mode_value),.adc_sdi(adc_sda),
 .clk_sclk(clk_sclk),.clk_sda(clk_sda),.clk_cs(clk_cs),.adc_sclk(adc_sclk),.adc_sdo(adc_sdo),.adc_sdo_enable(adc_oe),.adc_cs(adc_cs),
 .startup_finished(startup_finished),.config_busy(config_busy),.config_verified(config_verified),.active_mode(active_mode),.config_epoch(config_epoch),.diagnostic(live_diag),.result_toggle(result_toggle));
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] clock_done_sync=0;
 always @(posedge clk200)if(reset200)clock_done_sync<=0;else clock_done_sync<={clock_done_sync[1:0],startup_finished};
 reg [7:0] delay_count=0;
 always @(posedge clk200)if(reset200 || !clock_done_sync[2])delay_count<=0;else if(delay_count!=255)delay_count<=delay_count+1'b1;
 wire ctrl_reset=reset200 || delay_count!=255 || !clock_done_sync[2];
 wire clk_vec,delay_ready;wire [111:0] raw_words;
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] vector_reset_sync=7;
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [7:0] capture_vector_reset_sync=8'hFF;
 always @(posedge clk_vec or posedge ctrl_reset)if(ctrl_reset)vector_reset_sync<=7;else vector_reset_sync<={vector_reset_sync[1:0],1'b0};
 wire capture_reset_async=ctrl_reset || capture_reset25;
 always @(posedge clk_vec or posedge capture_reset_async)if(capture_reset_async)capture_vector_reset_sync<=8'hFF;else capture_vector_reset_sync<={capture_vector_reset_sync[6:0],1'b0};
 wire vector_reset=vector_reset_sync[2],capture_reset_vec=capture_vector_reset_sync[7];
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] delay_sync=0,verified_sync=0,config_busy_sync=7,clock_fault_sync=0;
 wire clock_fault;
 always @(posedge clk_vec)begin
  if(vector_reset)delay_sync<=0;else delay_sync<={delay_sync[1:0],delay_ready};
  if(capture_reset_vec)begin verified_sync<=0;config_busy_sync<=7;clock_fault_sync<=0;end
  else begin verified_sync<={verified_sync[1:0],config_verified};config_busy_sync<={config_busy_sync[1:0],config_busy};clock_fault_sync<={clock_fault_sync[1:0],clock_fault};end
 end
 reg [3:0] io_warmup=0;
 always @(posedge clk_vec)if(vector_reset || !delay_sync[2])io_warmup<=0;else if(io_warmup!=15)io_warmup<=io_warmup+1'b1;
 wire serdes_reset=vector_reset || io_warmup<8;
 adc_rx8 receive(.dco_p(adc_dco_p),.dco_n(adc_dco_n),.data_p(adc_data_p),.data_n(adc_data_n),
 .ref200(clk200),.ctrl_reset(ctrl_reset),.capture_reset(serdes_reset),.bitslip(1'b0),.clkdiv(clk_vec),.delay_ready(delay_ready),.words(raw_words));
 reg [111:0] captured_words=0;reg [31:0] vector_count=0;
 always @(posedge clk_vec)begin
  if(vector_reset)captured_words<=0;else captured_words<=raw_words;
  if(io_warmup!=15)vector_count<=0;else vector_count<=vector_count+1'b1;
 end
 // Completion mailbox transfers one coherent mode+readback, including failures.
 reg [31:0] published_epoch=0;
 wire config_mail_ready,config_mail_valid;wire [145:0] config_received;
 wire config_mail_send=config_mail_ready && !config_busy && config_epoch!=0 && config_epoch!=published_epoch;
 always @(posedge clk25)if(capture_reset25)published_epoch<=0;else if(config_mail_send)published_epoch<=config_epoch;
 tc_mailbox #(.WIDTH(146)) config_mailbox(.src_clk(clk25),.src_reset(capture_reset25),.src_send(config_mail_send),
 .src_data({config_epoch,config_verified,active_mode[0],live_diag}),.src_ready(config_mail_ready),
 .dst_clk(clk_vec),.dst_reset(capture_reset_vec),.dst_valid(config_mail_valid),.dst_data(config_received));
 reg mode_vec=1,mode_verified_vec=0,pending_training=0,train_restart=0,config_failed_pulse=0;
 reg [111:0] diagnostic_snapshot=0;reg [5:0] settle_vectors=0;
 reg training_timeout=0;reg [15:0] training_watchdog=0;
 wire train_valid,train_parity,train_failed;wire [15:0] train_count;
 wire stream_ready_vec=io_warmup==15 && settle_vectors==32 && mode_verified_vec && verified_sync[2] && !config_busy_sync[2] && !clock_fault_sync[2] && !capture_reset_vec;
 wire train_enable=stream_ready_vec && mode_vec && !pending_training;
 wire capture_stream_valid=stream_ready_vec && !pending_training && !train_restart && (!mode_vec || train_valid);
 always @(posedge clk_vec)begin
  if(capture_reset_vec)begin
   mode_vec<=1;mode_verified_vec<=0;pending_training<=0;train_restart<=0;config_failed_pulse<=0;
   diagnostic_snapshot<=0;settle_vectors<=0;training_timeout<=0;training_watchdog<=0;
  end else begin
   train_restart<=0;config_failed_pulse<=0;
   if(config_busy_sync[2] || !verified_sync[2] || io_warmup!=15)settle_vectors<=0;
   else if(settle_vectors<32)settle_vectors<=settle_vectors+1'b1;
   if(config_mail_valid)begin
    diagnostic_snapshot<=config_received[111:0];mode_vec<=config_received[112];mode_verified_vec<=config_received[113];
    settle_vectors<=0;pending_training<=config_received[113] && config_received[112];
    config_failed_pulse<=!config_received[113];training_watchdog<=0;
    if(config_received[113] && config_received[112])training_timeout<=0;
   end else if(pending_training && stream_ready_vec)begin train_restart<=1;pending_training<=0;training_watchdog<=0;end
   else if(train_enable && !train_valid && !train_failed)begin
    if(training_watchdog==65534)training_timeout<=1;else training_watchdog<=training_watchdog+1'b1;
   end
  end
 end
 tc_pn9_train trainer(.clk_vec(clk_vec),.reset(capture_reset_vec),.restart(train_restart),.enable(train_enable),
 .invalidate(config_failed_pulse || clock_fault_sync[2] || !delay_sync[2] || training_timeout),.words(captured_words),
 .valid(train_valid),.parity(train_parity),.failed(train_failed),.good_vectors(train_count));
 wire [31:0] ctrl_araddr;
 wire [2:0] ctrl_arprot;
 wire ctrl_arready;
 wire ctrl_arvalid;
 wire [31:0] ctrl_awaddr;
 wire [2:0] ctrl_awprot;
 wire ctrl_awready;
 wire ctrl_awvalid;
 wire ctrl_bready;
 wire [1:0] ctrl_bresp;
 wire ctrl_bvalid;
 wire [31:0] ctrl_rdata;
 wire ctrl_rready;
 wire [1:0] ctrl_rresp;
 wire ctrl_rvalid;
 wire [31:0] ctrl_wdata;
 wire ctrl_wready;
 wire [3:0] ctrl_wstrb;
 wire ctrl_wvalid;
 wire [31:0] ram_araddr;
 wire [2:0] ram_arprot;
 wire ram_arready;
 wire ram_arvalid;
 wire [31:0] ram_awaddr;
 wire [2:0] ram_awprot;
 wire ram_awready;
 wire ram_awvalid;
 wire ram_bready;
 wire [1:0] ram_bresp;
 wire ram_bvalid;
 wire [31:0] ram_rdata;
 wire ram_rready;
 wire [1:0] ram_rresp;
 wire ram_rvalid;
 wire [31:0] ram_wdata;
 wire ram_wready;
 wire [3:0] ram_wstrb;
 wire ram_wvalid;
 zynq_petaLinux_wrapper processing_system(
 .DDR_addr(DDR_addr),
 .DDR_ba(DDR_ba),
 .DDR_cas_n(DDR_cas_n),
 .DDR_ck_n(DDR_ck_n),
 .DDR_ck_p(DDR_ck_p),
 .DDR_cke(DDR_cke),
 .DDR_cs_n(DDR_cs_n),
 .DDR_dm(DDR_dm),
 .DDR_dq(DDR_dq),
 .DDR_dqs_n(DDR_dqs_n),
 .DDR_dqs_p(DDR_dqs_p),
 .DDR_odt(DDR_odt),
 .DDR_ras_n(DDR_ras_n),
 .DDR_reset_n(DDR_reset_n),
 .DDR_we_n(DDR_we_n),
 .FIXED_IO_ddr_vrn(FIXED_IO_ddr_vrn),
 .FIXED_IO_ddr_vrp(FIXED_IO_ddr_vrp),
 .FIXED_IO_mio(FIXED_IO_mio),
 .FIXED_IO_ps_clk(FIXED_IO_ps_clk),
 .FIXED_IO_ps_porb(FIXED_IO_ps_porb),
 .FIXED_IO_ps_srstb(FIXED_IO_ps_srstb),
 .M_AXI_CTRL_araddr(ctrl_araddr),
 .M_AXI_CTRL_arprot(ctrl_arprot),
 .M_AXI_CTRL_arready(ctrl_arready),
 .M_AXI_CTRL_arvalid(ctrl_arvalid),
 .M_AXI_CTRL_awaddr(ctrl_awaddr),
 .M_AXI_CTRL_awprot(ctrl_awprot),
 .M_AXI_CTRL_awready(ctrl_awready),
 .M_AXI_CTRL_awvalid(ctrl_awvalid),
 .M_AXI_CTRL_bready(ctrl_bready),
 .M_AXI_CTRL_bresp(ctrl_bresp),
 .M_AXI_CTRL_bvalid(ctrl_bvalid),
 .M_AXI_CTRL_rdata(ctrl_rdata),
 .M_AXI_CTRL_rready(ctrl_rready),
 .M_AXI_CTRL_rresp(ctrl_rresp),
 .M_AXI_CTRL_rvalid(ctrl_rvalid),
 .M_AXI_CTRL_wdata(ctrl_wdata),
 .M_AXI_CTRL_wready(ctrl_wready),
 .M_AXI_CTRL_wstrb(ctrl_wstrb),
 .M_AXI_CTRL_wvalid(ctrl_wvalid),
 .M_AXI_RAM_araddr(ram_araddr),
 .M_AXI_RAM_arprot(ram_arprot),
 .M_AXI_RAM_arready(ram_arready),
 .M_AXI_RAM_arvalid(ram_arvalid),
 .M_AXI_RAM_awaddr(ram_awaddr),
 .M_AXI_RAM_awprot(ram_awprot),
 .M_AXI_RAM_awready(ram_awready),
 .M_AXI_RAM_awvalid(ram_awvalid),
 .M_AXI_RAM_bready(ram_bready),
 .M_AXI_RAM_bresp(ram_bresp),
 .M_AXI_RAM_bvalid(ram_bvalid),
 .M_AXI_RAM_rdata(ram_rdata),
 .M_AXI_RAM_rready(ram_rready),
 .M_AXI_RAM_rresp(ram_rresp),
 .M_AXI_RAM_rvalid(ram_rvalid),
 .M_AXI_RAM_wdata(ram_wdata),
 .M_AXI_RAM_wready(ram_wready),
 .M_AXI_RAM_wstrb(ram_wstrb),
 .M_AXI_RAM_wvalid(ram_wvalid),
 .clk25(clk25),.axi_resetn(axi_resetn),.ps_resetn(ps_resetn));
 wire ctrl_wr_en,ctrl_wr_error,ctrl_rd_en,ctrl_rd_error;wire [31:0] ctrl_wr_addr,ctrl_wr_data,ctrl_rd_addr,ctrl_rd_data;wire [3:0] ctrl_wr_strb;
 tc_axil_frontend ctrl_frontend(.clk(clk25),.resetn(axi_resetn),
 .s_axi_araddr(ctrl_araddr),
 .s_axi_arprot(ctrl_arprot),
 .s_axi_arready(ctrl_arready),
 .s_axi_arvalid(ctrl_arvalid),
 .s_axi_awaddr(ctrl_awaddr),
 .s_axi_awprot(ctrl_awprot),
 .s_axi_awready(ctrl_awready),
 .s_axi_awvalid(ctrl_awvalid),
 .s_axi_bready(ctrl_bready),
 .s_axi_bresp(ctrl_bresp),
 .s_axi_bvalid(ctrl_bvalid),
 .s_axi_rdata(ctrl_rdata),
 .s_axi_rready(ctrl_rready),
 .s_axi_rresp(ctrl_rresp),
 .s_axi_rvalid(ctrl_rvalid),
 .s_axi_wdata(ctrl_wdata),
 .s_axi_wready(ctrl_wready),
 .s_axi_wstrb(ctrl_wstrb),
 .s_axi_wvalid(ctrl_wvalid),
.wr_en(ctrl_wr_en),.wr_addr(ctrl_wr_addr),.wr_data(ctrl_wr_data),.wr_strb(ctrl_wr_strb),.wr_error(ctrl_wr_error),.rd_en(ctrl_rd_en),.rd_addr(ctrl_rd_addr),.rd_data(ctrl_rd_data),.rd_error(ctrl_rd_error));
 wire ram_wr_en,ram_wr_error,ram_rd_en,ram_rd_error;wire [31:0] ram_wr_addr,ram_wr_data,ram_rd_addr,ram_rd_data;wire [3:0] ram_wr_strb;
 tc_axil_frontend ram_frontend(.clk(clk25),.resetn(axi_resetn),
 .s_axi_araddr(ram_araddr),
 .s_axi_arprot(ram_arprot),
 .s_axi_arready(ram_arready),
 .s_axi_arvalid(ram_arvalid),
 .s_axi_awaddr(ram_awaddr),
 .s_axi_awprot(ram_awprot),
 .s_axi_awready(ram_awready),
 .s_axi_awvalid(ram_awvalid),
 .s_axi_bready(ram_bready),
 .s_axi_bresp(ram_bresp),
 .s_axi_bvalid(ram_bvalid),
 .s_axi_rdata(ram_rdata),
 .s_axi_rready(ram_rready),
 .s_axi_rresp(ram_rresp),
 .s_axi_rvalid(ram_rvalid),
 .s_axi_wdata(ram_wdata),
 .s_axi_wready(ram_wready),
 .s_axi_wstrb(ram_wstrb),
 .s_axi_wvalid(ram_wvalid),
.wr_en(ram_wr_en),.wr_addr(ram_wr_addr),.wr_data(ram_wr_data),.wr_strb(ram_wr_strb),.wr_error(ram_wr_error),.rd_en(ram_rd_en),.rd_addr(ram_rd_addr),.rd_data(ram_rd_data),.rd_error(ram_rd_error));
 wire memory_write;wire [15:0] memory_address;wire [31:0] memory_data,training_status;wire [3:0] capture_phase;
 tc_capture_path capture_path(.clk25(clk25),.reset25(capture_reset25),.fault_reset25(reset25),.clk_vec(clk_vec),.reset_vec(capture_reset_vec),
 .words(captured_words),.stream_valid_vec(capture_stream_valid),.training_valid_vec(train_valid),.training_parity_vec(train_parity),.training_failed_vec(train_failed),.training_count_vec(train_count),
 .config_busy(config_busy),.config_verified(config_verified),.active_mode(active_mode),.config_epoch(config_epoch),.live_diag(live_diag),
 .wr_en(ctrl_wr_en),.wr_addr(ctrl_wr_addr),.wr_data(ctrl_wr_data),.wr_strb(ctrl_wr_strb),.wr_error(ctrl_wr_error),.rd_addr(ctrl_rd_addr),.rd_data(ctrl_rd_data),.rd_error(ctrl_rd_error),
 .mode_start(mode_start),.mode_value(mode_value),.ram_write(memory_write),.ram_address(memory_address),.ram_data(memory_data),.clock_fault(clock_fault),.capture_phase(capture_phase),.training_status(training_status));
 tc_snapshot_ram snapshot_memory(.clk(clk25),.resetn(axi_resetn),.capture_we(memory_write),.capture_word_address(memory_address),.capture_data(memory_data),
 .rd_en(ram_rd_en),.rd_addr(ram_rd_addr),.rd_data(ram_rd_data),.rd_error(ram_rd_error),.wr_error(ram_wr_error));
 // Same-clock ILA only. Raw digital data never crosses to clk25 outside FIFO.
 wire [7:0] status={train_failed,train_valid,mode_vec,settle_vectors==32,io_warmup==15,serdes_reset,delay_sync[2],mode_verified_vec};
 ila_tc capture(.clk(clk_vec),.probe0(captured_words),.probe1(vector_count),.probe2(status),.probe3(diagnostic_snapshot));
endmodule
