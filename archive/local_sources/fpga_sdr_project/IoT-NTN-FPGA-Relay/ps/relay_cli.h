/******************************************************************************
 * relay_cli.h -- UART command interface + live status line for the PL relay
 *
 * Included by main.c AFTER the globals (sample_rate, rx_lo_freq, tx_lo_freq,
 * gain, txatt, ad9361_phy) so the commands can change them at run time.
 *
 * Wiring: PS UART1 at 0xE0001000, 115200 8N1  (BSP STDIN/STDOUT)
 * Every command is terminated by CR or LF.  Replies are plain ASCII lines so
 * a host program can parse them easily.
 *
 *   help                 this list
 *   status               one STAT line
 *   auto <0|1>           periodic STAT line on/off
 *   mode <0..3>          0 bypass  1 relay  2 mute  3 duc-only
 *   ddc <val>            DDC NCO phase increment (dec, or 0x hex)
 *   duc <val>            DUC NCO phase increment
 *   off <hz>             DUC offset in Hz (uses the current sample_rate)
 *   xoff <hz>            DDC offset in Hz
 *   gain <0..0xFFF>      digital gain, Q1.11 (0x800 = 1.0)
 *   dc <0|1>             DC blocker enable (relay mode only)
 *   rxgain <db>          AD9361 RX gain, 0..76 dB
 *   txatt <db>           AD9361 TX attenuation, 0..89 dB
 *   lo <rxMHz> <txMHz>   change both local oscillators
 *   rate <MSPS>          change the sample rate (see the warning below)
 *   clear                clear the clip counter view (prints it once)
 *
 * !! WARNING about `rate`
 *    The DATA_CLK period in toppin.xdc is derived from the sample rate:
 *        period_ns = 4000 / sample_rate_in_MSPS      (2R2T mode)
 *    Changing the rate here without re-synthesising with a matching
 *    constraint can break the AD9361 LVDS interface.
 *****************************************************************************/
#ifndef RELAY_CLI_H_
#define RELAY_CLI_H_

#include "xuartps.h"

#define CLI_BUF_LEN 80

static char cli_buf[CLI_BUF_LEN];
static int  cli_len      = 0;
static int  cli_auto     = 1;      /* periodic status enabled */
static int  cli_last_rc  = 0;

/*----------------------- tiny string builder -----------------------------*/
static char cli_out[220];
static int  cli_out_len = 0;

static void co_c(char c)
{
    if (cli_out_len < (int)sizeof(cli_out) - 1) cli_out[cli_out_len++] = c;
}
static void co_s(const char *s) { while (*s) co_c(*s++); }
static void co_u(unsigned int v, int width)
{
    char t[12]; int n = 0;
    if (v == 0u) t[n++] = '0';
    while (v) { t[n++] = (char)('0' + (v % 10u)); v /= 10u; }
    while (n < width) t[n++] = '0';
    while (n) co_c(t[--n]);
}
static void co_i(int v)
{
    if (v < 0) { co_c('-'); co_u((unsigned int)(-v), 0); }
    else       co_u((unsigned int)v, 0);
}
static void co_h(unsigned int v, int digits)
{
    static const char *H = "0123456789ABCDEF";
    int i;
    for (i = digits - 1; i >= 0; i--) co_c(H[(v >> (i * 4)) & 0xFu]);
}
static void co_flush(void)
{
    cli_out[cli_out_len] = 0;
    printf("%s\r\n", cli_out);
    cli_out_len = 0;
}

/*----------------------- parsing helpers --------------------------------*/
static int tok_eq(const char *a, const char *b)
{
    while (*a && *b) { if (*a != *b) return 0; a++; b++; }
    return (*a == 0) && (*b == 0);
}

static unsigned int cli_num(const char *s)
{
    unsigned int v = 0;
    int neg = 0;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        s += 2;
        for (;;) {
            char c = *s++;
            unsigned int d;
            if (c >= '0' && c <= '9')      d = (unsigned int)(c - '0');
            else if (c >= 'a' && c <= 'f') d = (unsigned int)(c - 'a' + 10);
            else if (c >= 'A' && c <= 'F') d = (unsigned int)(c - 'A' + 10);
            else break;
            v = (v << 4) | d;
        }
    } else {
        if (*s == '-') { neg = 1; s++; }
        while (*s >= '0' && *s <= '9') v = v * 10u + (unsigned int)(*s++ - '0');
        if (neg) v = (unsigned int)(-(int)v);
    }
    return v;
}

/* "off" / "xoff" take a signed Hz value */
static int cli_snum(const char *s)
{
    int neg = 0;
    unsigned int v;
    if (*s == '-') { neg = 1; s++; }
    v = cli_num(s);
    return neg ? -(int)v : (int)v;
}

/* split "cmd arg1 arg2" -> argv[], returns argc */
static int cli_split(char *line, char **argv, int max)
{
    int n = 0;
    while (*line && n < max) {
        while (*line == ' ' || *line == '\t') line++;
        if (!*line) break;
        argv[n++] = line;
        while (*line && *line != ' ' && *line != '\t') line++;
        if (*line) *line++ = 0;
    }
    return n;
}

/*----------------------- status line ------------------------------------*/
static void cli_stat(void)
{
    unsigned int g = Xil_In32(R_RELAY_GAIN);
    co_s("STAT mode=");   co_u(Xil_In32(R_RELAY_MODE) & 3u, 0);
    co_s(" ddc=");        co_h(Xil_In32(R_RELAY_DDC_FREQ), 8);
    co_s(" duc=");        co_h(Xil_In32(R_RELAY_DUC_FREQ), 8);
    co_s(" gain=");       co_h(g & 0xFFFu, 3);
    co_s(" dc=");         co_u((g >> 12) & 1u, 0);
    co_s(" rxgain=");     co_i((int)gain);
    co_s(" txatt=");      co_i((int)(txatt / 1000u));
    co_s(" rxlo=");       co_u((unsigned int)(rx_lo_freq / 1000000ULL), 0);
    co_s(" txlo=");       co_u((unsigned int)(tx_lo_freq / 1000000ULL), 0);
    co_s(" fs=");         co_u(sample_rate, 0);
    co_s(" in=");         co_u(relay_get_sample_cnt(), 0);
    co_s(" out=");        co_u(relay_get_out_cnt(), 0);
    co_s(" clip=");       co_u(relay_get_clip_cnt(), 0);
    co_s(" rc=");         co_i(cli_last_rc);
    co_flush();
}

static void cli_help(void)
{
    co_s("# relay CLI ready. commands:");  co_flush();
    co_s("#  status | auto <0|1> | mode <0..3> | ddc <v> | duc <v>"); co_flush();
    co_s("#  off <hz> | xoff <hz> | gain <v> | dc <0|1>");            co_flush();
    co_s("#  rxgain <db> | txatt <db> | lo <rxMHz> <txMHz> | rate <MSPS>"); co_flush();
    co_s("#  mode: 0=bypass 1=relay 2=mute 3=duc_only");              co_flush();
}

static void cli_exec(char *line)
{
    char *av[6];
    int   ac = cli_split(line, av, 6);
    if (ac == 0) return;

    if (tok_eq(av[0], "help") || tok_eq(av[0], "?")) {
        cli_help();
    } else if (tok_eq(av[0], "status") || tok_eq(av[0], "r")) {
        cli_stat();
    } else if (tok_eq(av[0], "auto") && ac >= 2) {
        cli_auto = (int)cli_num(av[1]) ? 1 : 0;
        co_s("OK auto="); co_u((unsigned)cli_auto, 0); co_flush();
    } else if (tok_eq(av[0], "mode") && ac >= 2) {
        relay_set_mode(cli_num(av[1]) & 3u);
        co_s("OK mode="); co_u(cli_num(av[1]) & 3u, 0); co_flush();
    } else if (tok_eq(av[0], "ddc") && ac >= 2) {
        relay_set_ddc_freq(cli_num(av[1]));
        co_s("OK ddc="); co_h(cli_num(av[1]), 8); co_flush();
    } else if (tok_eq(av[0], "duc") && ac >= 2) {
        relay_set_duc_freq(cli_num(av[1]));
        co_s("OK duc="); co_h(cli_num(av[1]), 8); co_flush();
    } else if (tok_eq(av[0], "off") && ac >= 2) {
        unsigned int w = relay_freq_word(cli_snum(av[1]), sample_rate);
        relay_set_duc_freq(w);
        co_s("OK duc="); co_h(w, 8); co_flush();
    } else if (tok_eq(av[0], "xoff") && ac >= 2) {
        unsigned int w = relay_freq_word(cli_snum(av[1]), sample_rate);
        relay_set_ddc_freq(w);
        co_s("OK ddc="); co_h(w, 8); co_flush();
    } else if (tok_eq(av[0], "gain") && ac >= 2) {
        unsigned int g = Xil_In32(R_RELAY_GAIN);
        unsigned int nv = (g & 0x1000u) | (cli_num(av[1]) & 0xFFFu);
        Xil_Out32(R_RELAY_GAIN, nv);
        co_s("OK gain="); co_h(nv & 0xFFFu, 3); co_flush();
    } else if (tok_eq(av[0], "dc") && ac >= 2) {
        unsigned int g = Xil_In32(R_RELAY_GAIN);
        unsigned int nv = (g & 0xFFFu) | ((cli_num(av[1]) & 1u) << 12);
        Xil_Out32(R_RELAY_GAIN, nv);
        co_s("OK dc="); co_u((nv >> 12) & 1u, 0); co_flush();
    } else if (tok_eq(av[0], "rxgain") && ac >= 2) {
        gain = (int)cli_num(av[1]);
        ad9361_set_rx_rf_gain(ad9361_phy, 0, gain);
        ad9361_set_rx_rf_gain(ad9361_phy, 1, gain);
        co_s("OK rxgain="); co_i(gain); co_flush();
    } else if (tok_eq(av[0], "txatt") && ac >= 2) {
        txatt = cli_num(av[1]) * 1000u;
        ad9361_set_tx_attenuation(ad9361_phy, 0, txatt);
        ad9361_set_tx_attenuation(ad9361_phy, 1, txatt);
        co_s("OK txatt="); co_i((int)(txatt / 1000u)); co_flush();
    } else if (tok_eq(av[0], "lo") && ac >= 3) {
        rx_lo_freq = (u64)cli_num(av[1]) * 1000000ULL;
        tx_lo_freq = (u64)cli_num(av[2]) * 1000000ULL;
        ad9361_set_rx_lo_freq(ad9361_phy, rx_lo_freq);
        ad9361_set_tx_lo_freq(ad9361_phy, tx_lo_freq);
        co_s("OK rxlo="); co_u((unsigned int)(rx_lo_freq/1000000ULL),0);
        co_s(" txlo=");   co_u((unsigned int)(tx_lo_freq/1000000ULL),0);
        co_flush();
    } else if (tok_eq(av[0], "rate") && ac >= 2) {
        sample_rate = cli_num(av[1]) * 1000000u;
        ad9361_set_rx_sampling_freq(ad9361_phy, sample_rate);
        ad9361_set_tx_sampling_freq(ad9361_phy, sample_rate);
        co_s("OK fs="); co_u(sample_rate, 0);
        co_s(" (WARNING: toppin.xdc DATA_CLK period must match)"); co_flush();
    } else {
        co_s("ERR unknown command: "); co_s(av[0]); co_flush();
    }
}

/*----------------------- poll, call from the main loop ------------------*/
static int cli_ticks = 0;

static void cli_poll(void)
{
    /* ---- receive ---- */
    while (XUartPs_IsReceiveData(STDIN_BASEADDRESS)) {
        char c = (char)XUartPs_RecvByte(STDIN_BASEADDRESS);
        if (c == '\r' || c == '\n') {
            if (cli_len > 0) { cli_buf[cli_len] = 0; cli_exec(cli_buf); cli_len = 0; }
        } else if (c == 8 || c == 127) {
            if (cli_len > 0) cli_len--;
        } else if (cli_len < CLI_BUF_LEN - 1) {
            cli_buf[cli_len++] = c;
        }
    }

    /* ---- periodic status + mailbox ---- */
    cli_ticks++;
    if (cli_ticks >= 100000) {
        cli_ticks = 0;
        cli_last_rc = 0;
        relay_mailbox_update(0);
        if (cli_auto) cli_stat();
    }
}

#endif /* RELAY_CLI_H_ */
