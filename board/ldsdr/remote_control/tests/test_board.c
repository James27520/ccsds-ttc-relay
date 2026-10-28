#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "mocks/xtime_l.h"

#define RELAY_MODE_MUTE 2u
#define R_RELAY_MODE 16u
#define STDIN_BASEADDRESS 0u
static uint64_t ticks;
static unsigned mode,level_writes,enable_writes,legacy_calls,uart_pos,uart_n;
static unsigned first_event;
static uint32_t atten[2];
static uint32_t txatt;
static int32_t gain;
static int32_t gains[2];
static uint64_t rx_hz,tx_hz;
static int probe_ready=1,phy_object;
static int *ad9361_phy=&phy_object;
static volatile uint32_t relay_spi_error_count;
static int write_error,counter_error,read_error,radio_error,legacy_error,mode_error;
static const char *uart;
static int cli_last_rc;
static unsigned diag_calls,stat_calls;
struct relay_rf_command { uint16_t seq; uint64_t rx_hz,tx_hz; uint8_t rx_gain_db,tx_att_db; };
static void XTime_GetTime(XTime *value) { *value=ticks; }
static void relay_set_mode(unsigned value) {
    if(!first_event) first_event=1;
    if(value==1) ++enable_writes;
    if(!mode_error) mode=value;
}
static unsigned Xil_In32(unsigned addr) { assert(addr==R_RELAY_MODE); return mode; }
static int ad9361_set_rx_rf_gain(int *phy,unsigned ch,int32_t value) {
    assert(phy==ad9361_phy && ch<2);++level_writes;if(!first_event) first_event=2;
    gains[ch]=value;if(counter_error) ++relay_spi_error_count;return write_error;
}
static int ad9361_set_tx_attenuation(int *phy,unsigned ch,uint32_t value) {
    assert(phy==ad9361_phy && ch<2);++level_writes;if(!first_event) first_event=2;
    atten[ch]=value;if(counter_error) ++relay_spi_error_count;return write_error;
}
static int probe_read_lo(unsigned tx,uint64_t *value) {
    *value=tx?tx_hz:rx_hz;if(counter_error) ++relay_spi_error_count;return read_error;
}
static int probe_read_gain(unsigned ch,int32_t *value) {
    *value=gains[ch];if(counter_error) ++relay_spi_error_count;return read_error;
}
static int probe_read_atten(unsigned ch,uint32_t *value) {
    *value=atten[ch];if(counter_error) ++relay_spi_error_count;return read_error;
}
static int probe_radio_check(void) { if(counter_error) ++relay_spi_error_count;return radio_error; }
static int relay_apply_rf_command(const struct relay_rf_command *c) {
    ++legacy_calls;assert(mode==2);
    rx_hz=c->rx_hz;tx_hz=c->tx_hz;gains[0]=gains[1]=c->rx_gain_db;
    atten[0]=atten[1]=(uint32_t)c->tx_att_db*1000u;return legacy_error;
}
static unsigned XUartPs_IsReceiveData(unsigned base) { assert(!base);return uart_pos<uart_n; }
static unsigned XUartPs_RecvByte(unsigned base) { assert(!base);return (unsigned char)uart[uart_pos++]; }
static void cli_stat(void) { ++stat_calls; }
static void diag_rfdiag(void) { ++diag_calls;cli_last_rc=read_error; }
#include "relay_remote_board.h"

static void reset(void) {
    ticks=123456789;mode=2;level_writes=enable_writes=legacy_calls=first_event=0;
    atten[0]=atten[1]=89000;gains[0]=gains[1]=0;rx_hz=900000000;tx_hz=1000000000;
    probe_ready=1;ad9361_phy=&phy_object;relay_spi_error_count=0;
    write_error=counter_error=read_error=radio_error=legacy_error=mode_error=0;
    uart_pos=uart_n=0;uart="";remote_cli_length=remote_cli_overflow=0;
    diag_calls=stat_calls=0;cli_last_rc=0;
    remote_board_init();
}
static void feed(const char *s) { uart=s;uart_pos=0;uart_n=(unsigned)strlen(s); }
int main(void) {
    struct remote_snapshot v;
    struct relay_rf_command cmd={1,910000000,1010000000,20,60};
    reset();assert(first_event==1 && !remote_board.fault && level_writes==4);
    assert(remote_board_now(NULL)==0);
    ticks+=COUNTS_PER_SECOND+COUNTS_PER_SECOND/2;
    assert(remote_board_now(NULL)==1499); /* floor of actual fractional ticks */
    assert(!remote_board_read(NULL,&v) && v.mode==2 && v.attenuation[1]==89000);
    puts("PASS: real adapter time origin/fraction conversion, first mute and actual dual-channel reads");

    reset();counter_error=1;assert(remote_board_gain(NULL,0,30)==-1);
    assert(remote_board_attenuation(NULL,1,50000)==-1);
    assert(remote_board_read(NULL,&v)==-1 && remote_board_radio(NULL)==-1);
    counter_error=0;write_error=1;assert(remote_board_gain(NULL,0,0)==-1);
    write_error=0;mode_error=1;assert(remote_board_mode(NULL,1)==-1);
    puts("PASS: explicit errors, counter-only SPI errors and PL readback mismatch propagate");

    reset();assert(!remote_board_legacy(&cmd));
    assert(legacy_calls==1 && mode==2 && !remote_board.active && !enable_writes);
    assert(rx_hz==cmd.rx_hz && gains[0]==20 && atten[1]==60000);
    reset();legacy_error=1;assert(remote_board_legacy(&cmd)==-4);
    assert(remote_board.fault && mode==2 && !gains[0] && atten[0]==89000);
    reset();read_error=1;assert(remote_board_legacy(&cmd)==-4 && !legacy_calls && remote_board.fault);
    puts("PASS: old RF_SET preserves requested settings while muted and failures perform full safe stop");

    reset();feed("mode 1\n");remote_cli_poll();assert(!enable_writes && mode==2);
    feed("rxgain 30\n");remote_cli_poll();assert(gains[0]==0);
    feed("abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuv");remote_cli_poll();assert(uart_pos==16);
    remote_cli_poll();assert(uart_pos==32);remote_cli_poll();assert(uart_pos==48);
    feed("\nstop\n");remote_cli_poll();remote_cli_poll();assert(!remote_board.active && mode==2);
    feed("txatt 89\n");remote_cli_poll();assert(txatt==89000 && gain==0);
    feed("rxgain 0\n");remote_cli_poll();assert(txatt==89000 && gain==0);
    feed("rfdiag\n");remote_cli_poll();assert(diag_calls==1 && !remote_board.fault);
    feed("status\n");remote_cli_poll();assert(stat_calls==1);
    puts("PASS: UART write commands rejected, serial flooding bounded to 16 bytes and one command per pass");

    reset();ad9361_phy=NULL;assert(remote_board_read(NULL,&v)==-1);
    assert(remote_board_gain(NULL,0,30)==-1 && remote_board_attenuation(NULL,0,50000)==-1);
    ad9361_phy=&phy_object;probe_ready=0;assert(remote_board_read(NULL,&v)==-1);
    puts("PASS: unavailable/failed PHY initialization never dereferenced by the hardware adapter");
    return 0;
}
