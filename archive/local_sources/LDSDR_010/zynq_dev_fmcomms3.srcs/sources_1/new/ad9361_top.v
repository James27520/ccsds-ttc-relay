//ad9361 top
module ad9361_top(
            DDR_0_addr,
            DDR_0_ba,
            DDR_0_cas_n,
            DDR_0_ck_n,
            DDR_0_ck_p,
            DDR_0_cke,
            DDR_0_cs_n,
            DDR_0_dm,
            DDR_0_dq, 
            DDR_0_dqs_n,
            DDR_0_dqs_p,
            DDR_0_odt,
            DDR_0_ras_n,
            DDR_0_reset_n,
            DDR_0_we_n,
            FIXED_IO_0_ddr_vrn,
            FIXED_IO_0_ddr_vrp,
            FIXED_IO_0_mio,
            FIXED_IO_0_ps_clk,
            FIXED_IO_0_ps_porb,
            FIXED_IO_0_ps_srstb,
            //spi config
            spi_csn, 
            spi_clk, 
            spi_mosi,
            spi_miso,
            en_agc,    
            enable,    
            resetb,
            txnrx , 
//            sync_in ,  
            sys_clk,
            ctrl_in,
            tx_clk_out_n,    
            tx_clk_out_p,    
            tx_frame_out_n, 
            tx_frame_out_p,            
            tx_data_out_n,
            tx_data_out_p, 
            rx_clk_in_n,     
            rx_clk_in_p,     
            rx_frame_in_n, 
            rx_frame_in_p ,
            rx_data_in_n, 
            rx_data_in_p
   );
    inout [14:0]DDR_0_addr;
    inout [2:0]DDR_0_ba;
    inout DDR_0_cas_n;
    inout DDR_0_ck_n;
    inout DDR_0_ck_p;
    inout DDR_0_cke;
    inout DDR_0_cs_n;
    inout [3:0]DDR_0_dm;
    inout [31:0]DDR_0_dq;
    inout [3:0]DDR_0_dqs_n;
    inout [3:0]DDR_0_dqs_p;
    inout DDR_0_odt;
    inout DDR_0_ras_n;
    inout DDR_0_reset_n;
    inout DDR_0_we_n;
    inout FIXED_IO_0_ddr_vrn;
    inout FIXED_IO_0_ddr_vrp;
    inout [53:0]FIXED_IO_0_mio;
    inout FIXED_IO_0_ps_clk;
    inout FIXED_IO_0_ps_porb;
    inout FIXED_IO_0_ps_srstb; 
    output spi_csn;
    output spi_clk; 
    output spi_mosi;
    input spi_miso;
    //ad9361 control signal
    output en_agc;   
    output enable;    
    output resetb;
    output txnrx;
//    output sync_in; 
    output [3:0] ctrl_in;
    //data port tx chanel
    output tx_clk_out_n;   
    output tx_clk_out_p;    
    output tx_frame_out_n; 
    output tx_frame_out_p;           
    output [5:0]tx_data_out_n;
    output [5:0]tx_data_out_p; 
    //data port rx channel
    input rx_clk_in_n;   
    input rx_clk_in_p;   
    input rx_frame_in_n; 
    input rx_frame_in_p;
    input [5:0]rx_data_in_n; 
    input [5:0]rx_data_in_p;
    input sys_clk;
    wire [31:0]gpio_o;
  
    assign txnrx		=	gpio_o[0];
    assign enable		=	gpio_o[1];
    assign resetb		=	gpio_o[2];
//    assign sync_in		=	gpio_o[3];
    assign en_agc		=	gpio_o[4];
    assign ctrl_in		=	gpio_o[8:5];

	design_1_wrapper inst_design_1_wrapper
		(
			.DDR_0_addr            (DDR_0_addr),
			.DDR_0_ba              (DDR_0_ba),
			.DDR_0_cas_n           (DDR_0_cas_n),
			.DDR_0_ck_n            (DDR_0_ck_n),
			.DDR_0_ck_p            (DDR_0_ck_p),
			.DDR_0_cke             (DDR_0_cke),
			.DDR_0_cs_n            (DDR_0_cs_n),
			.DDR_0_dm              (DDR_0_dm),
			.DDR_0_dq              (DDR_0_dq),
			.DDR_0_dqs_n           (DDR_0_dqs_n),
			.DDR_0_dqs_p           (DDR_0_dqs_p),
			.DDR_0_odt             (DDR_0_odt),
			.DDR_0_ras_n           (DDR_0_ras_n),
			.DDR_0_reset_n         (DDR_0_reset_n),
			.DDR_0_we_n            (DDR_0_we_n),
			.FIXED_IO_0_ddr_vrn    (FIXED_IO_0_ddr_vrn),
			.FIXED_IO_0_ddr_vrp    (FIXED_IO_0_ddr_vrp),
			.FIXED_IO_0_mio        (FIXED_IO_0_mio),
			.FIXED_IO_0_ps_clk     (FIXED_IO_0_ps_clk),
			.FIXED_IO_0_ps_porb    (FIXED_IO_0_ps_porb),
			.FIXED_IO_0_ps_srstb   (FIXED_IO_0_ps_srstb),
			.GPIO_O_0              (gpio_o),
			.ILA_CLK               (sys_clk),
			.SPI0_MISO_I_0         (spi_miso),
			.SPI0_MOSI_O_0         (spi_mosi),
			.SPI0_SCLK_O_0         (spi_clk),
			.SPI0_SS_O_0           (spi_csn),
			
			.rx_clk_in_n_0         (rx_clk_in_n),
			.rx_clk_in_p_0         (rx_clk_in_p),
			.rx_data_in_n_0        (rx_data_in_n),
			.rx_data_in_p_0        (rx_data_in_p),
			.rx_frame_in_n_0       (rx_frame_in_n),
			.rx_frame_in_p_0       (rx_frame_in_p),
			.tx_clk_out_n_0        (tx_clk_out_n),
			.tx_clk_out_p_0        (tx_clk_out_p),
			.tx_data_out_n_0       (tx_data_out_n),
			.tx_data_out_p_0       (tx_data_out_p),
			.tx_frame_out_n_0      (tx_frame_out_n),
			.tx_frame_out_p_0      (tx_frame_out_p)
		);
endmodule
