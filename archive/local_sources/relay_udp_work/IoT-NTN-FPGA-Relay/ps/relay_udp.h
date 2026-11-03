#ifndef RELAY_UDP_H
#define RELAY_UDP_H

#include <stdio.h>
#include <string.h>
#include "xparameters.h"
#include "xil_exception.h"
#include "xscugic.h"
#include "xtime_l.h"
#include "lwip/init.h"
#include "lwip/udp.h"
#include "lwip/etharp.h"
#include "netif/xadapter.h"
#include "relay_rf_control.h"

#define RELAY_UDP_PORT 5005u

static struct netif relay_netif;
static struct udp_pcb *relay_udp_pcb;
static XTime relay_arp_last;

static void relay_udp_reply(struct udp_pcb *pcb, const ip_addr_t *addr, u16_t port,
                            int rc, unsigned seq)
{
    char msg[96];
    struct pbuf *out;
    int n = snprintf(msg, sizeof(msg), "rc=%d seq=%u rx_hz=%llu tx_hz=%llu\n",
                     rc, seq, (unsigned long long)rx_lo_freq,
                     (unsigned long long)tx_lo_freq);
    if (n <= 0 || n >= (int)sizeof(msg)) return;
    out = pbuf_alloc(PBUF_TRANSPORT, (u16_t)n, PBUF_RAM);
    if (!out) return;
    memcpy(out->payload, msg, (size_t)n);
    udp_sendto(pcb, out, addr, port);
    pbuf_free(out);
}

static void relay_udp_receive(void *arg, struct udp_pcb *pcb, struct pbuf *p,
                              const ip_addr_t *addr, u16_t port)
{
    uint8_t bytes[RELAY_RF_PACKET_SIZE];
    struct relay_rf_command cmd;
    int rc;
    unsigned seq = 0;
    ip_addr_t peer;
    (void)arg;
    if (!p) return;
    ip_addr_copy(peer, *addr);
    if (p->tot_len != sizeof(bytes) ||
        pbuf_copy_partial(p, bytes, sizeof(bytes), 0) != sizeof(bytes)) {
        rc = -1;
    } else {
        rc = relay_parse_rf_packet(bytes, sizeof(bytes), &cmd);
        if (!rc) {
            seq = cmd.seq;
            rc = relay_apply_rf_command(&cmd);
        }
    }
    pbuf_free(p);
    relay_udp_reply(pcb, &peer, port, rc, seq);
    printf("UDP RF_SET rc=%d seq=%u rxlo=%u txlo=%u\r\n", rc, seq,
           (unsigned)(rx_lo_freq / 1000000ULL),
           (unsigned)(tx_lo_freq / 1000000ULL));
}

static int relay_udp_init(void)
{
    ip_addr_t ip, mask, gateway;
    unsigned char mac[6] = {0x02, 0x4c, 0x44, 0x53, 0x44, 0x52};

    if (XScuGic_DeviceInitialize(XPAR_SCUGIC_SINGLE_DEVICE_ID) != 0)
        return -1;
    Xil_ExceptionInit();
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_IRQ_INT,
        (Xil_ExceptionHandler)XScuGic_DeviceInterruptHandler,
        (void *)XPAR_SCUGIC_SINGLE_DEVICE_ID);

    IP4_ADDR(&ip, 169, 254, 9, 10);
    IP4_ADDR(&mask, 255, 255, 0, 0);
    IP4_ADDR(&gateway, 0, 0, 0, 0);
    lwip_init();
    if (!xemac_add(&relay_netif, &ip, &mask, &gateway, mac,
                   XPAR_XEMACPS_0_BASEADDR)) return -2;
    netif_set_default(&relay_netif);
    netif_set_up(&relay_netif);
    relay_udp_pcb = udp_new();
    if (!relay_udp_pcb) return -3;
    if (udp_bind(relay_udp_pcb, IP_ADDR_ANY, RELAY_UDP_PORT) != ERR_OK) {
        udp_remove(relay_udp_pcb);
        relay_udp_pcb = NULL;
        return -4;
    }
    udp_recv(relay_udp_pcb, relay_udp_receive, NULL);
    Xil_ExceptionEnableMask(XIL_EXCEPTION_IRQ);
    XTime_GetTime(&relay_arp_last);
    printf("UDP RF_SET ready: 169.254.9.10:%u\r\n", RELAY_UDP_PORT);
    return 0;
}

static void relay_udp_poll(void)
{
    XTime now;
    if (!relay_udp_pcb) return;
    xemacif_input(&relay_netif);
    XTime_GetTime(&now);
    if (now - relay_arp_last >= (XTime)5 * COUNTS_PER_SECOND) {
        etharp_tmr();
        relay_arp_last = now;
    }
}

#endif
