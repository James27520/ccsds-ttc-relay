/* ADDA-specific standalone Cortex-A9 platform. No PS7 initialization here:
 * cold/warm loader must supply the matching ADDA XSA initialization first.
 * Default image permits UART/selftests/network but will not touch absent M2
 * capture registers until rebuilt with ADDA_CAPTURE_ENABLED=1 for matched PL. */
#include "adda_controller.h"
#include "adda_pattern_check.h"
#include "adda_telemetry_tx.h"
#include "adda_service.h"
#include "xparameters.h"
#include "xuartps.h"
#include "xuartps_hw.h"
#include "xtime_l.h"
#include "xil_io.h"
#include "xil_mmu.h"
#include "xil_cache.h"
#include "xil_exception.h"
#include "xscugic.h"
#include "lwip/init.h"
#include "lwip/udp.h"
#include "lwip/pbuf.h"
#include "lwip/tcp.h"
#include "lwip/priv/tcp_priv.h"
#include "lwip/etharp.h"
#include "lwip/ip4_frag.h"
#include "netif/xadapter.h"
#include "netif/xemacpsif.h"
#include <stdio.h>
#include <string.h>
#ifndef ADDA_CAPTURE_ENABLED
#define ADDA_CAPTURE_ENABLED 0
#endif
static struct aps_state core;
static struct ac_capture capture;
static struct act_controller controller;
static struct atm_tx telemetry_tx;
static struct asv_service service;
static int16_t adc_samples[TC_SAMPLE_COUNT] __attribute__((aligned(64)));
static XUartPs uart;
static XScuGic gic;
static struct netif network;
static struct udp_pcb *udp;
static unsigned network_stack_initialized,network_initialized,network_enabled;
static uint32_t tcp_last,arp_last,reass_last,link_last,rx_last;
/* BSP crt0 owns reset/startup; pure C application has no extra crt init work. */
void _init(void){}
void _fini(void){}
static uint32_t clock_ms(void *context)
{XTime ticks;(void)context;XTime_GetTime(&ticks);return (uint32_t)(ticks/(COUNTS_PER_SECOND/1000u));}
static void uart_log(void *context,const char *text)
{(void)context;while(*text)XUartPs_SendByte(XPAR_XUARTPS_0_BASEADDR,(uint8_t)*text++);}
static int uart_init(void)
{
    XUartPs_Config *cfg=XUartPs_LookupConfig(XPAR_XUARTPS_0_DEVICE_ID);
    XUartPsFormat format;
    if(!cfg || XUartPs_CfgInitialize(&uart,cfg,cfg->BaseAddress)!=XST_SUCCESS)return -1;
    format.BaudRate=115200;format.DataBits=XUARTPS_FORMAT_8_BITS;
    format.Parity=XUARTPS_FORMAT_NO_PARITY;format.StopBits=XUARTPS_FORMAT_1_STOP_BIT;
    if(XUartPs_SetDataFormat(&uart,&format)!=XST_SUCCESS)return -1;
    XUartPs_SetOperMode(&uart,XUARTPS_OPER_MODE_NORMAL);return 0;
}
static void memory_barrier(void *context){(void)context;__asm__ volatile("dsb sy" ::: "memory");}
static int read32(void *context,uint32_t address,uint32_t *value)
{(void)context;*value=Xil_In32(address);return 0;}
static int write32(void *context,uint32_t address,uint32_t value)
{(void)context;Xil_Out32(address,value);return 0;}
static void receive_udp(void *arg,struct udp_pcb *pcb,struct pbuf *p,const ip_addr_t *peer,u16_t port)
{
    uint8_t bytes[128];uint16_t n;(void)arg;(void)pcb;
    if(!p)return;
    n=p->tot_len;
    if(network_enabled && n<sizeof(bytes) && IP_IS_V4(peer) && pbuf_copy_partial(p,bytes,n,0)==n)
        (void)aps_udp_received(&core,lwip_ntohl(ip4_addr_get_u32(ip_2_ip4(peer))),port,bytes,n);
    pbuf_free(p);
}
static int send_udp(void *context,uint32_t peer,uint16_t port,const uint8_t *bytes,size_t length)
{
    ip_addr_t dest;struct pbuf *p;err_t rc;(void)context;
    if(!network_enabled || !udp || !netif_is_link_up(&network) || length>65535u)return -1;
    IP_ADDR4(&dest,(peer>>24)&255u,(peer>>16)&255u,(peer>>8)&255u,peer&255u);
    p=pbuf_alloc(PBUF_TRANSPORT,(u16_t)length,PBUF_RAM);if(!p)return -2;
    rc=pbuf_take(p,bytes,(u16_t)length);
    if(rc==ERR_OK)rc=udp_sendto(udp,p,&dest,port);
    pbuf_free(p);return (int)rc;
}
static int network_on(void)
{
    ip_addr_t ip,mask,gw;unsigned char mac[6]={0x02,0,0,0,9,0x11};
    XScuGic_Config *cfg;
    if(core.transaction.pending)return AP_EBUSY;
    if(!network_stack_initialized) {
        cfg=XScuGic_LookupConfig(XPAR_SCUGIC_SINGLE_DEVICE_ID);
        if(!cfg || XScuGic_CfgInitialize(&gic,cfg,cfg->CpuBaseAddress)!=XST_SUCCESS)return -1;
        Xil_ExceptionInit();Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_INT,
          (Xil_ExceptionHandler)XScuGic_InterruptHandler,&gic);
        lwip_init();network_stack_initialized=1u;
    }
    if(!network_initialized) {
        /* Failed netif_add attempts reuse lwIP pools only after the port has
         * released its allocations; never reset a live stack to hide leaks. */
        Xil_ExceptionDisable();memset(&network,0,sizeof(network));
        IP_ADDR4(&ip,169,254,9,11);IP_ADDR4(&mask,255,255,0,0);IP_ADDR4(&gw,0,0,0,0);
        uart_log(0,"NETWORK_INIT explicit request; bounded PHY reset/autoneg wait\r\n");
        if(!xemac_add(&network,&ip,&mask,&gw,mac,XPAR_XEMACPS_0_BASEADDR)) {
            network_enabled=0u;aps_set_network_ready(&core,0u);
            memset(&network,0,sizeof(network));
            uart_log(0,"NETWORK_FAILED init; network=OFF ready=0; retry network on\r\n");
            return -2;
        }
        network_initialized=1u;netif_set_default(&network);
        Xil_ExceptionEnable();
    }
    if(!udp) {
        udp=udp_new();if(!udp)return -3;
        if(udp_bind(udp,IP_ADDR_ANY,5006u)!=ERR_OK){udp_remove(udp);udp=0;return -4;}
        udp_recv(udp,receive_udp,0);
    }
    netif_set_up(&network);network_enabled=1u;
    eth_link_detect(&network);aps_set_network_ready(&core,netif_is_link_up(&network));
    tcp_last=arp_last=reass_last=link_last=rx_last=clock_ms(0);
    uart_log(0,"NETWORK_ON local=169.254.9.11:5006 mask=255.255.0.0 peer=169.254.9.10:5005 MAC=02:00:00:00:09:11; no RF_SET requested\r\n");
    return 0;
}
static void network_off(void)
{
    (void)asv_stop(&service,ASV_USER,clock_ms(0));
    (void)atm_tx_stop(&telemetry_tx);
    network_enabled=0u;controller.automatic=0u;core.armed=0u;aps_set_network_ready(&core,0u);
    if(network_initialized)netif_set_down(&network);
    uart_log(0,"NETWORK_OFF auto=OFF armed=OFF\r\n");
}
static void network_poll(void)
{
    uint32_t t;if(!network_initialized)return;
    (void)xemacif_input(&network);if(!network_enabled)return;
    t=clock_ms(0);
    if((uint32_t)(t-tcp_last)>=250u){tcp_tmr();tcp_last=t;}
    if((uint32_t)(t-arp_last)>=5000u){etharp_tmr();arp_last=t;}
    if((uint32_t)(t-reass_last)>=1000u){ip_reass_tmr();reass_last=t;}
    if((uint32_t)(t-rx_last)>=100u){xemacpsif_resetrx_on_no_rxdata(&network);rx_last=t;}
    if((uint32_t)(t-link_last)>=1000u){eth_link_detect(&network);aps_set_network_ready(&core,netif_is_link_up(&network));link_last=t;}
}
static void line_command(char *line)
{
    int rc,cancel_rc=AP_OK;char text[384];
    if(asv_cancel_command(line))cancel_rc=asv_stop(&service,ASV_USER,clock_ms(0));
    if(!strcmp(line,"service status")) {
        rc=asv_status(&service,clock_ms(0),text,sizeof(text));
        if(rc>=0){uart_log(0,text);rc=AP_OK;}
    }
    else if(!strcmp(line,"service on"))rc=asv_start(&service,clock_ms(0));
    else if(!strcmp(line,"service off"))rc=asv_stop(&service,ASV_USER,clock_ms(0));
    else if(!asv_command_allowed(&service,line)) {
        uart_log(0,"SERVICE_BUSY conflicting command rejected\r\n");rc=AP_EBUSY;
    }
    else if(!strcmp(line,"network on"))rc=network_on();
    else if(!strcmp(line,"network off")){network_off();rc=0;}
    else if(!strcmp(line,"tmstatus")) {
        uint32_t status=0u,diag=0u;
        rc=atm_tx_status(&telemetry_tx,&status,&diag);
        (void)snprintf(text,sizeof(text),"TM_TX enabled=%u seq=%lu pending=%u stopping=%u status=%08lx diag=%08lx\r\n",
          (unsigned)ADDA_TM_TX_ENABLED,(unsigned long)telemetry_tx.sequence,telemetry_tx.pending,
          telemetry_tx.stopping,(unsigned long)status,(unsigned long)diag);uart_log(0,text);
        if(rc==0) {
            uint32_t cfg=0,cfg_diag=0;
            rc=atm_tx_configuration(&telemetry_tx,&cfg,&cfg_diag);
            (void)snprintf(text,sizeof(text),"TM_DAC verified=%u finished=%u diagnostic=%08lx rc=%d\r\n",
              (unsigned)(cfg&1u),(unsigned)((cfg>>1)&1u),(unsigned long)cfg_diag,rc);uart_log(0,text);
        }
    }
    else if(!strcmp(line,"tmsend")) {
        rc=atm_tx_send(&telemetry_tx,&core,clock_ms(0));
        if(rc<0)uart_log(0,"TM_TX rejected; inspect tmstatus; stopped/sticky fault requires explicit tmclear before tmsend\r\n");
    }
    else if(!strcmp(line,"tmstop"))rc=atm_tx_stop(&telemetry_tx);
    else if(!strcmp(line,"tmclear"))rc=atm_tx_clear(&telemetry_tx);
    else {
        if(!strcmp(line,"help"))uart_log(0,"network on/off | service on/off/status (600s,16 transactions,400 finite replies each) | tmstatus | tmsend | tmstop | tmclear (explicit idle recovery)\r\n");
        rc=act_command_line(&controller,line);
    }
    if(cancel_rc<0)rc=cancel_rc;
    (void)snprintf(text,sizeof(text),"CLI_RESULT rc=%d\r\n",rc);uart_log(0,text);
}
int main(void)
{
    struct aps_io io={0,uart_log,send_udp};struct ac_io mmio={0,read32,write32,memory_barrier};
    struct atm_io tm_io={0,read32,write32,memory_barrier};
    struct ac_policy policy={TC_FRAMEWORK_BUILD_ID,TC_TRAIN_ALGO_PN9,6u,4u};
    struct act_clock clock={0,clock_ms};char line[128];unsigned used=0u,discard=0u;uint8_t ch;
    uint32_t published_epoch=0u;char info[240];
    if(uart_init()!=0)return 1;
    XTime_SetTime(0); /* This application owns core0; core1 must remain parked. */
    Xil_ICacheEnable();Xil_DCacheEnable();
    if(ADDA_CAPTURE_ENABLED) {
        Xil_SetTlbAttributes(TC_CTRL_BASE,DEVICE_MEMORY);
        Xil_SetTlbAttributes(TC_BRAM_BASE,DEVICE_MEMORY);memory_barrier(0);
    }
    if(ADDA_TM_TX_ENABLED) {Xil_SetTlbAttributes(ATM_TX_BASE,DEVICE_MEMORY);memory_barrier(0);}
    aps_init(&core,&io);ac_init(&capture,&mmio,&policy,adc_samples,TC_SAMPLE_COUNT);
    act_init(&controller,&core,ADDA_CAPTURE_ENABLED?&capture:0,&clock);
    (void)atm_tx_init(&telemetry_tx,&tm_io);
    asv_init(&service,&controller,&telemetry_tx);
    uart_log(0,ADDA_TM_TX_ENABLED?"TM_TX opt-in build; matching telemetry PL required; startup STOP, service OFF\r\n":
      "TM_TX disabled; DAC registers never accessed by this image\r\n");
    uart_log(0,ADDA_CAPTURE_ENABLED?
      "BOOT ADDA M2 candidate UART115200/8N1 capture=ENABLED no auto/network; matching final PL required\r\n":
      "BOOT ADDA PS candidate UART115200/8N1 capture=DISABLED; selftest/waveformtest local SYNTHETIC\r\n");
    for(;;) {
        /* ACK processing precedes retries, captures and synchronous decoding. */
        network_poll();
        (void)atm_tx_poll(&telemetry_tx,core.network_ready,clock_ms(0));
        while(XUartPs_IsReceiveData(XPAR_XUARTPS_0_BASEADDR)) {
            ch=XUartPs_ReadReg(XPAR_XUARTPS_0_BASEADDR,XUARTPS_FIFO_OFFSET)&255u;
            if(ch=='\r' || ch=='\n') {
                if(discard)uart_log(0,"CLI_REJECT overlength/control byte\r\n");
                else if(used){line[used]=0;line_command(line);}
                used=discard=0u;
            } else if(ch==8u || ch==127u) {if(used && !discard)--used;}
            else if(ch>=32u && ch<127u) {
                if(used<sizeof(line)-1u && !discard)line[used++]=(char)ch;else discard=1u;
            } else discard=1u;
        }
        asv_poll(&service,clock_ms(0));
        act_poll(&controller);
        if(capture.valid && capture.state==AC_READY && capture.snapshot.epoch!=published_epoch) {
            /* External debugger DDR reads do not snoop dirty CPU cache lines. */
            Xil_DCacheFlushRange((INTPTR)adc_samples,TC_CAPTURE_BYTES);memory_barrier(0);
            published_epoch=capture.snapshot.epoch;
            (void)snprintf(info,sizeof(info),"SNAPSHOT_DDR address=0x%08lx bytes=%lu epoch=%lu config_epoch=%lu source=%s channel=%lu k=%lu first=%d last=%d\r\n",
              (unsigned long)(UINTPTR)adc_samples,(unsigned long)TC_CAPTURE_BYTES,(unsigned long)published_epoch,
              (unsigned long)capture.snapshot.config_epoch,ac_normal_ready(&capture)?"ADC_NORMAL":"ADC_TEST",
              (unsigned long)(capture.snapshot.select&TC_SELECT_CHANNEL_MASK),
              (unsigned long)((capture.snapshot.select&TC_SELECT_K_MASK)>>TC_SELECT_K_SHIFT),
              (int)adc_samples[0],(int)adc_samples[TC_SAMPLE_COUNT-1]);uart_log(0,info);
            if(!ac_normal_ready(&capture)) {
                struct apc_result check;int pass=apc_check(adc_samples,TC_SAMPLE_COUNT,
                  (unsigned)(capture.snapshot.select&TC_SELECT_CHANNEL_MASK),&check);
                (void)snprintf(info,sizeof(info),"PATTERN_%s source=ADC_TEST count=%lu transitions=%lu errors=%lu zero_states=%lu invalid=%lu toggle=0x%04lx first=0x%04lx last=0x%04lx\r\n",
                  pass==1?"PASS":"FAIL",(unsigned long)check.samples,(unsigned long)check.transitions,
                  (unsigned long)check.mismatches,(unsigned long)check.zero_states,(unsigned long)check.invalid_samples,
                  (unsigned long)check.toggle_mask,(unsigned long)check.first_raw,(unsigned long)check.last_raw);uart_log(0,info);
            }
        }
    }
}
