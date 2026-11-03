/* Integration of the real board poller with MMIO/clock/radio mocks.
 * This does not claim physical RF or timing validation. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#define RELAY_BASE 0x43c00000u
#define R_RELAY_MODE (RELAY_BASE+16)
#include "relay_doppler.h"
static uint32_t now_ms,regs[16],seq,ram[2][RD_SAMPLES];
static unsigned busy,probe_ready=1;
static uint32_t relay_spi_error_count;
static int phy;
static int *ad9361_phy=&phy;
static struct { unsigned active,fault; uint64_t deadline; } remote_board;
static void rd_board_off(void);
static uint64_t remote_board_now(void *unused) {(void)unused;return now_ms;}
static void remote_tick(void *unused)
{(void)unused;if(remote_board.active && now_ms>=remote_board.deadline){remote_board.active=0;regs[4]=regs[11]=2;rd_board_off();}}
static int remote_safe(void *unused)
{(void)unused;remote_board.active=0;regs[4]=regs[11]=2;rd_board_off();return 0;}
static int probe_read_lo(unsigned tx,uint64_t *f) {*f=tx?2179000000ULL:1989000000ULL;return 0;}
static int ad9361_get_rx_sampling_freq(int *p,uint32_t *fs) {(void)p;*fs=RD_FS;return 0;}
static int ad9361_get_tx_sampling_freq(int *p,uint32_t *fs) {return ad9361_get_rx_sampling_freq(p,fs);}
static uint32_t Xil_In32(uint32_t addr)
{
 if(addr>=RELAY_BASE && addr<RELAY_BASE+64) return regs[(addr-RELAY_BASE)/4];
 switch(addr-0x43c10000u){case 0:return 0x44505131;case 4:return busy?1:seq?2:0;case 12:return RD_SAMPLES;case 16:return seq;case 20:return 1;}
 if(addr>=0x43c14000u && addr<0x43c18000u)return ram[0][(addr-0x43c14000u)/4];
 if(addr>=0x43c18000u && addr<0x43c1c000u)return ram[1][(addr-0x43c18000u)/4];
 assert(0);return 0;
}
static void Xil_Out32(uint32_t addr,uint32_t value)
{
 if(addr>=RELAY_BASE && addr<RELAY_BASE+64){regs[(addr-RELAY_BASE)/4]=value;return;}
 assert(addr==0x43c10008u && value==1);++seq;
}
#include "relay_doppler_board.h"
int main(void)
{
 unsigned ch,k;
 for(ch=0;ch<2;++ch)for(k=0;k<RD_SAMPLES;++k){
  double p=6.283185307179586*(ch?490000.:510000.)*k/RD_FS;
  int i=(int)lround(200*cos(p)),q=(int)lround(200*sin(p));
  ram[ch][k]=((uint32_t)i&4095)|(((uint32_t)q&4095)<<16);
 }
 rd_board_init();assert(rd_ready && !rd_channels[0].enabled);
 rd_board_cli("dp radial 1 1989500000 2179500000 -1500 0 1000 0 1000");assert(!rd_channels[0].enabled);
 remote_board.active=1;remote_board.deadline=2000;regs[4]=regs[11]=1;
 rd_board_cli("dp radial 1 1989500000 2179500000 -1500 0 1000 0 1000");
 rd_board_cli("dp radial 2 1989500000 2179500000 1500 0 -1000 0 1000");
 assert(rd_channels[0].enabled && rd_channels[1].enabled);
 rd_board_poll(); assert(rd_capture && seq==1);
 for(k=0;k<64;++k)rd_board_poll();
 assert(!rd_capture && rd_channels[0].incoming.accepted==1 && rd_channels[1].incoming.accepted==1);
 now_ms=50;rd_board_poll();assert(regs[5]!=0 && regs[12]!=0);
 now_ms=2000;rd_board_poll();assert(!rd_channels[0].enabled && !rd_channels[1].enabled && !regs[5] && !regs[12]);
 // Lease re-enable must NOT resurrect an expired Doppler plan.
 remote_board.active=1;remote_board.deadline=5000;regs[4]=regs[11]=1;
 rd_board_poll();assert(!regs[5] && !regs[12]);
 rd_board_cli("dp radial 1 1989500000 2179500000 -1500 0 1000 0 1000");
 rd_board_poll();busy=1;now_ms+=25;rd_board_poll();
 assert(!rd_capture && rd_rejected>0); // bounded stalled capture
 rd_board_cli("dp off");assert(!rd_channels[0].enabled && !regs[5]);
 puts("BOARD_DOPPLER_PASS: local model, actual poller, dual raw IQ, lease/off cleanup, bounded capture stall");
 return 0;
}
