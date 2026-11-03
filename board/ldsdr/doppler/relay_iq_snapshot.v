`timescale 1ns / 1ps
// Side tap only: never stalls or modifies ADC/DAC valid or data.
// Two frozen, 4096-sample snapshots. Producer owns RAM until the completion
// toggle crosses to AXI; consumer must finish reading before another request.
module relay_iq_snapshot #(
    parameter integer ADDR_BITS=12
) (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET s_axi_aresetn" *)
    input wire s_axi_aclk,
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *) input wire s_axi_aresetn,
    input wire [15:0] s_axi_awaddr, input wire [2:0] s_axi_awprot,
    input wire s_axi_awvalid, output wire s_axi_awready,
    input wire [31:0] s_axi_wdata, input wire [3:0] s_axi_wstrb,
    input wire s_axi_wvalid, output wire s_axi_wready,
    output reg [1:0] s_axi_bresp, output reg s_axi_bvalid, input wire s_axi_bready,
    input wire [15:0] s_axi_araddr, input wire [2:0] s_axi_arprot,
    input wire s_axi_arvalid, output wire s_axi_arready,
    output reg [31:0] s_axi_rdata, output reg [1:0] s_axi_rresp,
    output reg s_axi_rvalid, input wire s_axi_rready,
    input wire dq_clk,
    input wire valid1, input wire [11:0] i1, input wire [11:0] q1,
    input wire valid2, input wire [11:0] i2, input wire [11:0] q2
);
    localparam integer N=1<<ADDR_BITS;
    (* ram_style="block" *) reg [31:0] ram1[0:N-1];
    (* ram_style="block" *) reg [31:0] ram2[0:N-1];
    reg request, ack, capture;
    (* ASYNC_REG="TRUE" *) reg [1:0] req_sync, ack_sync, reset_sync;
    reg [ADDR_BITS:0] count1,count2;
    wire busy=request!=ack_sync[1];
    reg ack_seen;
    reg [31:0] capture_seq;
    // No asynchronous data bus crosses: completed RAM is frozen until the
    // next explicit request. Two-flop synchronizers carry ownership only.
    always @(posedge dq_clk or negedge s_axi_aresetn)
        if(!s_axi_aresetn) reset_sync<=0; else reset_sync<={reset_sync[0],1'b1};
    always @(posedge dq_clk) begin
        if(!reset_sync[1]) begin
            req_sync<=0; ack<=0; capture<=0; count1<=0; count2<=0;
        end else begin
            req_sync<={req_sync[0],request};
            if(!capture && req_sync[1]!=ack) begin
                capture<=1; count1<=0; count2<=0;
            end else if(capture) begin
                if(valid1 && count1<N) count1<=count1+1'b1;
                if(valid2 && count2<N) count2<=count2+1'b1;
                if(count1==N && count2==N) begin capture<=0; ack<=req_sync[1]; end
            end
        end
    end
    always @(posedge dq_clk) begin
        if(reset_sync[1] && capture && valid1 && count1<N)
            ram1[count1[ADDR_BITS-1:0]]<={4'b0,q1,4'b0,i1};
        if(reset_sync[1] && capture && valid2 && count2<N)
            ram2[count2[ADDR_BITS-1:0]]<={4'b0,q2,4'b0,i2};
    end
    reg aw_hold,w_hold;
    reg [15:0] aw;
    reg [31:0] wd;
    reg [3:0] ws;
    assign s_axi_awready=!aw_hold && !s_axi_bvalid;
    assign s_axi_wready=!w_hold && !s_axi_bvalid;
    reg pending;
    reg [1:0] bank;
    reg [31:0] register_data,ram_data1,ram_data2;
    reg read_bad;
    assign s_axi_arready=!pending && !s_axi_rvalid;
    wire take_read=s_axi_arvalid && s_axi_arready;
    always @(posedge s_axi_aclk) begin
        if(take_read) begin
            ram_data1<=ram1[s_axi_araddr[ADDR_BITS+1:2]];
            ram_data2<=ram2[s_axi_araddr[ADDR_BITS+1:2]];
        end
    end
    always @(posedge s_axi_aclk) begin
        if(!s_axi_aresetn) begin
            request<=0; ack_sync<=0; ack_seen<=0; capture_seq<=0;
            aw_hold<=0; w_hold<=0; s_axi_bvalid<=0; s_axi_bresp<=0;
            pending<=0; s_axi_rvalid<=0; s_axi_rresp<=0; s_axi_rdata<=0;
            aw<=0; wd<=0; ws<=0; bank<=0; register_data<=0; read_bad<=0;
        end else begin
            ack_sync<={ack_sync[0],ack};
            if(ack_sync[1]!=ack_seen) begin ack_seen<=ack_sync[1]; capture_seq<=capture_seq+1'b1; end
            if(s_axi_awvalid && s_axi_awready) begin aw<=s_axi_awaddr; aw_hold<=1; end
            if(s_axi_wvalid && s_axi_wready) begin wd<=s_axi_wdata; ws<=s_axi_wstrb; w_hold<=1; end
            if(s_axi_bvalid && s_axi_bready) s_axi_bvalid<=0;
            if(aw_hold && w_hold && !s_axi_bvalid) begin
                aw_hold<=0; w_hold<=0; s_axi_bvalid<=1; s_axi_bresp<=2'b10;
                if(aw==16'h0008 && ws==4'hf && wd==1 && !busy) begin
                    request<=!request; s_axi_bresp<=0;
                end
            end
            if(s_axi_rvalid && s_axi_rready) s_axi_rvalid<=0;
            if(take_read) begin
                pending<=1; bank<=s_axi_araddr[15:14]; register_data<=0; read_bad<=0;
                if(s_axi_araddr[1:0]!=0) read_bad<=1;
                if(s_axi_araddr[15:14]!=0) begin
                    if(busy || capture_seq==0 || s_axi_araddr[15:14]==3 ||
                       (s_axi_araddr[13:2]>=N)) read_bad<=1;
                end else case(s_axi_araddr)
                    16'h0000: register_data<=32'h44505131; // DPQ1
                    16'h0004: register_data<={30'b0,(capture_seq!=0 && !busy),busy};
                    16'h000c: register_data<=N;
                    16'h0010: register_data<=capture_seq;
                    16'h0014: register_data<=32'd1; // ABI version
                    default: read_bad<=1;
                endcase
            end
            if(pending) begin
                pending<=0; s_axi_rvalid<=1; s_axi_rresp<=read_bad?2'b10:2'b00;
                s_axi_rdata<=read_bad?0:bank==1?ram_data1:bank==2?ram_data2:register_data;
            end
        end
    end
    wire unused_prot=^s_axi_awprot ^ ^s_axi_arprot;
endmodule
