#ifndef RELAY_REMOTE_UDP_H
#define RELAY_REMOTE_UDP_H
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
#include "relay_remote_board.h"

#define RELAY_UDP_PORT 5005u
static struct netif relay_netif;
static struct udp_pcb *relay_udp_pcb;
static XTime relay_arp_last;
static void remote_udp_send(struct udp_pcb *pcb,const ip_addr_t *addr,u16_t port,
                             const void *bytes,u16_t n) {
    struct pbuf *out=pbuf_alloc(PBUF_TRANSPORT,n,PBUF_RAM);
    if(!out) return;
    memcpy(out->payload,bytes,n); (void)udp_sendto(pcb,out,addr,port); pbuf_free(out);
}
static void relay_udp_receive(void *arg,struct udp_pcb *pcb,struct pbuf *p,
                              const ip_addr_t *addr,u16_t port) {
    uint8_t bytes[REMOTE_COMMAND_SIZE]={0},ack[REMOTE_ACK_SIZE];
    u16_t n,copied; ip_addr_t peer; int rc;
    (void)arg; if(!p) return;
    ip_addr_copy(peer,*addr); n=p->tot_len;
    copied=n>sizeof(bytes)?sizeof(bytes):n;
    if(pbuf_copy_partial(p,bytes,copied,0)!=copied) n=0;
    pbuf_free(p);
    remote_tick(&remote_board);
    /* No malformed new-format command is passed to the legacy RF_SET path. */
    if(n==RELAY_RF_PACKET_SIZE && remote_u16(bytes)==0x0101u) {
        struct relay_rf_command cmd; unsigned seq=0; char reply[96]; int size;
        rc=relay_parse_rf_packet(bytes,n,&cmd);
        if(!rc) { seq=cmd.seq; rc=remote_board_legacy(&cmd); }
        size=snprintf(reply,sizeof(reply),"rc=%d seq=%u rx_hz=%llu tx_hz=%llu\n",
            rc,seq,(unsigned long long)rx_lo_freq,(unsigned long long)tx_lo_freq);
        if(size>0 && size<(int)sizeof(reply)) remote_udp_send(pcb,&peer,port,reply,(u16_t)size);
    } else {
        (void)remote_process(&remote_board,bytes,n,ack);
        remote_udp_send(pcb,&peer,port,ack,REMOTE_ACK_SIZE);
    }
    remote_tick(&remote_board);
}
static int relay_udp_init(void) {
    ip_addr_t ip,mask,gateway;
    unsigned char mac[6]={0x02,0x4c,0x44,0x53,0x44,0x52};
    if(XScuGic_DeviceInitialize(XPAR_SCUGIC_SINGLE_DEVICE_ID)!=0) return -1;
    Xil_ExceptionInit();
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_IRQ_INT,
        (Xil_ExceptionHandler)XScuGic_DeviceInterruptHandler,(void *)XPAR_SCUGIC_SINGLE_DEVICE_ID);
    IP4_ADDR(&ip,169,254,9,10); IP4_ADDR(&mask,255,255,0,0); IP4_ADDR(&gateway,0,0,0,0);
    lwip_init();
    if(!xemac_add(&relay_netif,&ip,&mask,&gateway,mac,XPAR_XEMACPS_0_BASEADDR)) return -2;
    netif_set_default(&relay_netif); netif_set_up(&relay_netif);
    relay_udp_pcb=udp_new(); if(!relay_udp_pcb) return -3;
    if(udp_bind(relay_udp_pcb,IP_ADDR_ANY,RELAY_UDP_PORT)!=ERR_OK) {
        udp_remove(relay_udp_pcb); relay_udp_pcb=NULL; return -4;
    }
    udp_recv(relay_udp_pcb,relay_udp_receive,NULL); Xil_ExceptionEnableMask(XIL_EXCEPTION_IRQ);
    XTime_GetTime(&relay_arp_last);
    printf("REMOTE UDP ready: 169.254.9.10:5005 leased control v1 MUTED\r\n"); return 0;
}
static void relay_udp_poll(void) {
    XTime now;
    remote_tick(&remote_board);
    if(!relay_udp_pcb) return;
    /* Hash-pinned bare-metal xemacpsif_input consumes at most one packet. */
    (void)xemacif_input(&relay_netif);
    remote_tick(&remote_board); XTime_GetTime(&now);
    if(now-relay_arp_last>=(XTime)5*COUNTS_PER_SECOND) { etharp_tmr(); relay_arp_last=now; }
    remote_tick(&remote_board);
}
#endif
