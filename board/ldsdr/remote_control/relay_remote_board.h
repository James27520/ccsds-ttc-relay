#ifndef RELAY_REMOTE_BOARD_H
#define RELAY_REMOTE_BOARD_H
#include "xtime_l.h"
#include "relay_remote_control.h"

static XTime remote_boot_ticks;
static struct remote_state remote_board;
static uint64_t remote_board_now(void *unused) {
    XTime now, elapsed;
    (void)unused; XTime_GetTime(&now); elapsed=now-remote_boot_ticks;
    return (elapsed/COUNTS_PER_SECOND)*1000ULL+
           ((elapsed%COUNTS_PER_SECOND)*1000ULL)/COUNTS_PER_SECOND;
}
static int remote_board_mode(void *unused,unsigned mode) {
    (void)unused; relay_set_mode(mode);
    return (Xil_In32(R_RELAY_MODE)&3u)==mode ? 0 : -1;
}
static int remote_board_gain(void *unused,unsigned ch,unsigned value) {
    uint32_t before=relay_spi_error_count; int rc;
    (void)unused;
    if(!ad9361_phy || !probe_ready) return -1;
    rc=ad9361_set_rx_rf_gain(ad9361_phy,ch,(int32_t)value);
    if(rc || relay_spi_error_count!=before) return -1;
    gain=(int32_t)value; return 0;
}
static int remote_board_attenuation(void *unused,unsigned ch,uint32_t value) {
    uint32_t before=relay_spi_error_count; int rc;
    (void)unused;
    if(!ad9361_phy || !probe_ready) return -1;
    rc=ad9361_set_tx_attenuation(ad9361_phy,ch,value);
    if(rc || relay_spi_error_count!=before) return -1;
    txatt=value; return 0;
}
static int remote_board_read(void *unused,struct remote_snapshot *v) {
    int32_t g0=0,g1=0; int bad=0;
    uint32_t before=relay_spi_error_count;
    (void)unused;
    v->mode=(uint8_t)(Xil_In32(R_RELAY_MODE)&3u);
    if(!ad9361_phy || !probe_ready) return -1;
    if(probe_read_lo(0,&v->rx_hz)) bad=1;
    if(probe_read_lo(1,&v->tx_hz)) bad=1;
    if(probe_read_gain(0,&g0)) bad=1;
    if(probe_read_gain(1,&g1)) bad=1;
    if(probe_read_atten(0,&v->attenuation[0])) bad=1;
    if(probe_read_atten(1,&v->attenuation[1])) bad=1;
    if(g0<0 || g0>76 || g1<0 || g1>76 || relay_spi_error_count!=before) bad=1;
    v->gain[0]=(uint8_t)g0; v->gain[1]=(uint8_t)g1;
    return bad ? -1 : 0;
}
static int remote_board_radio(void *unused) {
    uint32_t before=relay_spi_error_count; int rc;
    (void)unused; rc=probe_radio_check();
    return rc || relay_spi_error_count!=before ? -1 : 0;
}
static void remote_board_init(void) {
    struct remote_hardware hw={NULL,remote_board_now,remote_board_mode,
        remote_board_gain,remote_board_attenuation,remote_board_read,remote_board_radio};
    XTime_GetTime(&remote_boot_ticks); remote_init(&remote_board,&hw);
    (void)remote_safe(&remote_board);
}
/* Legacy packets retain their wire format and requested RF settings, but lose
 * any live lease before tuning and can never restore an enabled PL mode. */
static int remote_board_legacy(const struct relay_rf_command *cmd) {
    uint32_t before; struct remote_snapshot v; int rc;
    if(remote_safe(&remote_board)) return -4;
    before=relay_spi_error_count; rc=relay_apply_rf_command(cmd);
    relay_set_mode(RELAY_MODE_MUTE);
    if(rc || relay_spi_error_count!=before || remote_read(&remote_board,&v) ||
       v.mode!=2 || !remote_close(v.rx_hz,cmd->rx_hz) || !remote_close(v.tx_hz,cmd->tx_hz) ||
       v.gain[0]!=cmd->rx_gain_db || v.gain[1]!=cmd->rx_gain_db ||
       v.attenuation[0]!=(uint32_t)cmd->tx_att_db*1000u ||
       v.attenuation[1]!=(uint32_t)cmd->tx_att_db*1000u) {
        (void)remote_safe(&remote_board); remote_board.fault=1; return -4;
    }
    return 0;
}
/* This new image intentionally exposes only status and stop over UART. The old
 * CLI code remains in the fixed reconstruction but its dispatcher is unused. */
static char remote_cli_line[32];
static unsigned remote_cli_length,remote_cli_overflow;
static void remote_cli_exec(void) {
    struct remote_snapshot v;
    if(!strcmp(remote_cli_line,"stop") || !strcmp(remote_cli_line,"mode 2") ||
       !strcmp(remote_cli_line,"txatt 89") || !strcmp(remote_cli_line,"rxgain 0")) {
        int rc=remote_safe(&remote_board);
        printf("REMOTE stop rc=%d\r\n",rc);
    } else if(!strcmp(remote_cli_line,"status") || !strcmp(remote_cli_line,"r")) {
        int rc=remote_snapshot(&remote_board,&v);
        cli_last_rc=rc;
        cli_stat(); /* Keep the fixed STAT line for existing quiet/exit clients. */
        printf("REMOTE status rc=%d flags=%u mode=%u rx1=%u rx2=%u tx1=%lu tx2=%lu lease_ms=%lu\r\n",
            rc,v.flags,v.mode,v.gain[0],v.gain[1],(unsigned long)v.attenuation[0],
            (unsigned long)v.attenuation[1],(unsigned long)v.remaining_ms);
    } else if(!strcmp(remote_cli_line,"rfdiag")) {
        uint32_t before=relay_spi_error_count;
        remote_tick(&remote_board); diag_rfdiag();
        if(cli_last_rc || relay_spi_error_count!=before) {
            (void)remote_safe(&remote_board); remote_board.fault=1;
        }
        remote_tick(&remote_board);
    } else if(!strcmp(remote_cli_line,"help") || !strcmp(remote_cli_line,"?")) {
        printf("REMOTE UART: status | rfdiag | stop | mode 2 | txatt 89 | rxgain 0\r\n");
    } else printf("ERR REMOTE UART writes disabled; use leased UDP\r\n");
}
static void remote_cli_poll(void) {
    unsigned budget=16;
    while(budget-- && XUartPs_IsReceiveData(STDIN_BASEADDRESS)) {
        char c=(char)XUartPs_RecvByte(STDIN_BASEADDRESS);
        if(c=='\r' || c=='\n') {
            if(remote_cli_length && !remote_cli_overflow) {
                remote_cli_line[remote_cli_length]=0; remote_cli_exec();
            }
            remote_cli_length=remote_cli_overflow=0;
            break; /* At most one response (and its finite UART drain) per pass. */
        }
        if(c==8 || c==127) { if(remote_cli_length) --remote_cli_length; }
        else if(remote_cli_length<sizeof(remote_cli_line)-1) remote_cli_line[remote_cli_length++]=c;
        else remote_cli_overflow=1;
    }
}
#endif
