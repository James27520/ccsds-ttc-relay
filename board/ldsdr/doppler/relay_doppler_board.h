#ifndef RELAY_DOPPLER_BOARD_H
#define RELAY_DOPPLER_BOARD_H
/* Included after relay_remote_udp.h in the opt-in image only. No ISR work.
 * Requires the matching DPQ1 PL image at 0x43c10000 (Device memory).
 * Never load this image against an unknown PL address map. */
#include "relay_doppler.h"
#include <stdlib.h>
#define RD_BASE 0x43c10000u
static struct rd_channel rd_channels[2];
static struct rd_measurement rd_measured[2];
static struct dp_output rd_in[2],rd_out[2];
static uint32_t rd_iq[2][RD_SAMPLES];
static unsigned rd_ready,rd_capture,rd_index;
static uint32_t rd_request_ms,rd_next_ms,rd_apply_ms,rd_seq,rd_capture_seq;
static unsigned rd_rejected,rd_max_age_ms;
static uint32_t rd_reg(unsigned ch,unsigned duc)
{ return RELAY_BASE+(ch?(duc?0x34u:0x30u):(duc?0x18u:0x14u)); }
static uint32_t rd_now(void) { return (uint32_t)remote_board_now(NULL); }
static void rd_board_off(void)
{
    unsigned ch;
    for(ch=0;ch<2;++ch) if(rd_channels[ch].enabled) {
        /* Do not overwrite a new owner of the legacy NCO registers. */
        if(Xil_In32(rd_reg(ch,0))==rd_channels[ch].last_ddc)
            Xil_Out32(rd_reg(ch,0),rd_channels[ch].base_ddc);
        rd_channels[ch].enabled=0;
        dp_set_mode(&rd_channels[ch].incoming,DP_OFF);
        dp_set_mode(&rd_channels[ch].outgoing,DP_OFF);
    }
    rd_capture=0;
}
static void rd_board_init(void)
{
    uint32_t rxfs=0,txfs=0;
    rd_init(&rd_channels[0],0); rd_init(&rd_channels[1],1);
    rd_ready=probe_ready && !(Xil_In32(RELAY_BASE+0xc)&1u) && Xil_In32(RD_BASE)==0x44505131u &&
        Xil_In32(RD_BASE+0x14)==1 && Xil_In32(RD_BASE+0xc)==RD_SAMPLES &&
        !ad9361_get_rx_sampling_freq(ad9361_phy,&rxfs) &&
        !ad9361_get_tx_sampling_freq(ad9361_phy,&txfs) && rxfs==RD_FS && txfs==RD_FS;
    printf("DOPPLER business ready=%u default=OFF fs=%lu\r\n",rd_ready,(unsigned long)rxfs);
}
static void rd_board_cli(const char *line)
{
    unsigned ch,ttl; double fi,fo,vi,ai,vo,ao; char trailing;
    uint64_t rx=0,tx=0; uint32_t before=relay_spi_error_count;
    if(!strcmp(line,"dp off")) { rd_board_off(); printf("DOPPLER OFF\r\n"); return; }
    if(!strcmp(line,"dp status")) {
        for(ch=0;ch<2;++ch) printf("DOPPLER ch=%u on=%u state=%u in_hz=%ld out_hz=%ld measured_hz=%ld quality=%u accepted=%lu rejected=%lu max_age_ms=%u\r\n",
            ch+1,rd_channels[ch].enabled,(unsigned)rd_in[ch].state,
            (long)rd_in[ch].total_hz,(long)rd_out[ch].total_hz,(long)rd_measured[ch].cfo_hz,
            (unsigned)(1000*rd_measured[ch].coherence),(unsigned long)rd_channels[ch].incoming.accepted,
            (unsigned long)(rd_rejected+rd_channels[ch].incoming.rejected),rd_max_age_ms);
        return;
    }
    /* RF frequencies in Hz, radial speed m/s (positive=receding), radial
     * acceleration m/s^2; local epoch starts HERE, not at desktop send time. */
    if(sscanf(line,"dp radial %u %lf %lf %lf %lf %lf %lf %u %c",
        &ch,&fi,&fo,&vi,&ai,&vo,&ao,&ttl,&trailing)!=8 || ch<1 || ch>2 ||
        !rd_ready || !remote_board.active || remote_board.fault || rd_capture ||
        Xil_In32(RD_BASE+4)&1u) {
        printf("ERR DOPPLER needs active lease, idle capture, valid radial plan\r\n"); return;
    }
    remote_tick(&remote_board);
    if(!remote_board.active || probe_read_lo(0,&rx) || probe_read_lo(1,&tx) ||
       relay_spi_error_count!=before || Xil_In32(R_RELAY_MODE)!=1 ||
       (Xil_In32(RELAY_BASE+0x2c)&3u)!=1) {
        printf("ERR DOPPLER RF state\r\n"); return;
    }
    --ch;
    if(rd_channels[ch].enabled) {printf("ERR DOPPLER off before new model\r\n");return;}
    if(rd_configure(&rd_channels[ch],rd_now(),ttl,fi,fo,(double)rx,(double)tx,
        vi,ai,vo,ao,Xil_In32(rd_reg(ch,0)),Xil_In32(rd_reg(ch,1)))) {
        printf("ERR DOPPLER invalid model or frequency plan\r\n"); return;
    }
    rd_apply_ms=rd_now()-50u; rd_next_ms=rd_now();
    printf("DOPPLER ch=%u armed locally ttl_ms=%u; lease unchanged\r\n",ch+1,ttl);
}
static void rd_board_poll(void)
{
    unsigned ch,k; uint32_t now=rd_now(),word,status;
    if(!rd_ready || !(rd_channels[0].enabled || rd_channels[1].enabled)) return;
    /* The lease is checked even while incrementally copying capture RAM. */
    remote_tick(&remote_board);
    if(!remote_board.active || remote_board.fault ||
       (Xil_In32(RELAY_BASE+0xc)&1u) ||
       Xil_In32(R_RELAY_MODE)!=1 || (Xil_In32(RELAY_BASE+0x2c)&3u)!=1) {
        rd_board_off(); return;
    }
    for(ch=0;ch<2;++ch) if(rd_channels[ch].enabled &&
        (Xil_In32(rd_reg(ch,0))!=rd_channels[ch].last_ddc ||
         Xil_In32(rd_reg(ch,1))!=rd_channels[ch].base_duc)) {
        rd_board_off(); printf("ERR DOPPLER NCO ownership changed\r\n"); return;
    }
    if((uint32_t)(now-rd_apply_ms)>=50) {
        rd_apply_ms=now;
        for(ch=0;ch<2;++ch) if(rd_channels[ch].enabled) {
            int rc=rd_step(&rd_channels[ch],now,1,&word,&rd_in[ch],&rd_out[ch]);
            Xil_Out32(rd_reg(ch,0),word);
            if(Xil_In32(rd_reg(ch,0))!=word) {
                /* Readback failure is a hardware fault, not a new RF enable. */
                (void)remote_safe(&remote_board); remote_board.fault=1; return;
            }
            if(rc<0) printf("DOPPLER ch=%u model expired; baseline restored\r\n",ch+1);
        }
    }
    status=Xil_In32(RD_BASE+4);
    if(rd_capture) {
        if(status&1u) {
            if((uint32_t)(now-rd_request_ms)>20) {++rd_rejected;rd_capture=0;}
            return;
        }
        if(rd_index==0) {
            rd_capture_seq=Xil_In32(RD_BASE+0x10);
            if(rd_capture_seq==rd_seq) return;
            rd_seq=rd_capture_seq;
        }
        // Bounded copy: yield to networking/lease logic every 128 words.
        for(k=0;k<128 && rd_index<2*RD_SAMPLES;++k,++rd_index)
            rd_iq[rd_index/RD_SAMPLES][rd_index%RD_SAMPLES]=
                Xil_In32(RD_BASE+(rd_index<RD_SAMPLES?0x4000u:0x8000u)+4*(rd_index%RD_SAMPLES));
        if(rd_index==2*RD_SAMPLES) {
            rd_capture=0;
            for(ch=0;ch<2;++ch) if(rd_channels[ch].enabled) {
                uint32_t age;
                rd_measure(rd_iq[ch],RD_SAMPLES,RD_FS,rd_channels[ch].nominal_if_hz,&rd_measured[ch]);
                now=rd_now(); age=now-rd_request_ms;
                if(age>rd_max_age_ms) rd_max_age_ms=age;
                // Request time bounds capture epoch to <20 ms, including decode.
                if(age<=20) rd_observe(&rd_channels[ch],&rd_measured[ch],rd_request_ms,now,rd_seq);
                else ++rd_rejected;
            }
        }
    } else if(!(status&1u) && (int32_t)(now-rd_next_ms)>=0) {
        rd_request_ms=now; rd_next_ms=now+100; rd_index=0; rd_capture=1;
        Xil_Out32(RD_BASE+8,1);
    }
}
#endif
