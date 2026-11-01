/* Native frame -> PS -> exact UDP Hz -> ACK -> ATM2/TM2 tests. No hardware. */
#include "adda_telemetry_tx.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint8_t sent[34];static size_t sent_length;static unsigned sends;
static int send_udp(void *context,uint32_t peer,uint16_t port,const uint8_t *p,size_t n)
{(void)context;assert(peer==APS_RELAY_IPV4 && port==5005u && (n==26u || n==34u));memcpy(sent,p,n);sent_length=n;++sends;return 0;}
static void p32(uint8_t *p,uint32_t v){p[0]=(uint8_t)(v>>24);p[1]=(uint8_t)(v>>16);p[2]=(uint8_t)(v>>8);p[3]=(uint8_t)v;}
static void p64(uint8_t *p,uint64_t v){p32(p,(uint32_t)(v>>32));p32(p+4,(uint32_t)v);}
static uint64_t g64(const uint8_t *p){uint64_t v=0;unsigned i;for(i=0;i<8;++i)v=(v<<8)|p[i];return v;}
static void crc(uint8_t *p){uint16_t c=ap_crc16(p,48);p[48]=(uint8_t)(c>>8);p[49]=(uint8_t)c;}
static struct ap_frame_result frame(uint8_t version,uint16_t rx,uint16_t tx,uint8_t seq)
{
    struct ap_command c={version,rx,tx,seq};struct ap_frame_result f;uint8_t bits[160];
    assert(ap_frame_encode(&c,bits)==AP_OK && ap_find_frame(bits,sizeof(bits),0,&f)==AP_OK);
    return f;
}
static void ack(uint8_t *p,const struct aps_state *s,uint8_t operation,uint64_t rx,uint64_t tx,int rc)
{
    memset(p,0,50);p[0]=2;p[1]=0x20;p[2]=(uint8_t)(0xc0u|(s->transaction.pending_transaction_seq>>8));
    p[3]=(uint8_t)s->transaction.pending_transaction_seq;p[5]=43;p[6]=1;p[7]=operation;p[8]=1;p[9]=2;
    p32(p+12,89000);p32(p+16,89000);p32(p+24,12345);p64(p+28,rx);p64(p+36,tx);p32(p+44,(uint32_t)rc);crc(p);
}
static void check_tm2(const struct aps_state *s)
{
    char text[APS_TM1_MAX_BYTES],*tail;unsigned expected;int n=aps_telemetry_format(s,42,text,sizeof(text));
    assert(n>0 && n<1024 && !strncmp(text,"TM2 ",4) && !strstr(text,"_mhz="));
    tail=strstr(text," crc16=");assert(tail && sscanf(tail," crc16=%x",&expected)==1);
    assert(ap_crc16((const uint8_t *)text,(size_t)(tail-text))==expected);
    assert(strstr(text,"d_version=") && strstr(text,"d_rx_raw=") && strstr(text,"a_tx_hz="));
}
int main(void)
{
    struct aps_state s;struct aps_io io={0,0,send_udp};struct ap_frame_result f;
    uint8_t payload[112],reply[50],burst[484];char text[1024];unsigned i;
    const uint64_t rx=UINT64_C(1991845000),tx=UINT64_C(2192956000);
    aps_init(&s,&io);s.network_ready=s.armed=1;f=frame(0x81,12345,23456,37);
    assert(aps_accept_decoded(&s,&f,APS_SYNTHETIC,0)==AP_OK && !sends);
    assert(aps_accept_decoded(&s,&f,APS_ADC_NORMAL,0)==AP_OK && sends==1 && sent_length==26);
    assert(g64(sent+6)==rx && g64(sent+14)==tx && sent[1]==1);
    assert(atm_pack(&s,1,0,payload,sizeof(payload))==112 && payload[6]==0x81 && payload[7]==0x81);
    assert(payload[38]==0x30 && payload[39]==0x39 && payload[40]==0x5b && payload[41]==0xa0);
    aps_poll(&s,250);assert(sends==2 && !memcmp(sent,s.transaction.packet,26));
    (void)snprintf(text,sizeof(text),"rc=0 seq=1 rx_hz=%llu tx_hz=%llu\n",(unsigned long long)(rx+1000u),(unsigned long long)tx);
    assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,(const uint8_t *)text,strlen(text))==AP_EMISMATCH && s.transaction.pending);
    (void)snprintf(text,sizeof(text),"rc=0 seq=1 rx_hz=%llu tx_hz=%llu\n",(unsigned long long)(rx+10u),(unsigned long long)(tx-10u));
    assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,(const uint8_t *)text,strlen(text))==AP_OK && s.applied_commands==1);
    /* Frequency ATM2 has no relay snapshot even if stale memory contains one. */
    s.last_ack.status.flags=15;s.last_ack.status.mode=1;
    assert(atm_pack(&s,2,300,payload,sizeof(payload))==112 && payload[55]==0x81 && g64(payload+76)==rx+10u);
    for(i=92;i<112;++i)assert(!payload[i]);check_tm2(&s);
    assert(atm_burst(&s,2,300,burst,sizeof(burst))==484 && burst[10]==112);
    f=frame(0xa1,12346,23455,38);assert(aps_accept_decoded(&s,&f,APS_ADC_NORMAL,400)==AP_OK && sent_length==34);
    assert(sent[7]==0x21 && g64(sent+16)==rx+1000u && g64(sent+24)==tx-1000u);
    ack(reply,&s,0x21,rx+1000u,tx-989u,0);reply[8]=3;reply[9]=1;reply[10]=reply[11]=30;
    p32(reply+12,50000);p32(reply+16,50000);p32(reply+20,299990);crc(reply);
    assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,reply,sizeof(reply))==AP_EMISMATCH && s.transaction.pending);
    p64(reply+36,tx-990u);crc(reply);assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,reply,sizeof(reply))==AP_OK);
    assert(atm_pack(&s,3,450,payload,sizeof(payload))==112 && payload[55]==0xa1 && payload[95]==3);check_tm2(&s);
    f=frame(0xa2,0,0,39);assert(aps_accept_decoded(&s,&f,APS_ADC_NORMAL,500)==AP_OK);
    assert(sent[7]==0x22 && g64(sent+16)==AP_RX_BASE_HZ && g64(sent+24)==AP_TX_BASE_HZ);
    ack(reply,&s,0x22,UINT64_C(70000000),UINT64_C(6000000000),0);
    assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,reply,sizeof(reply))==AP_OK && s.applied_commands==3);
    assert(atm_pack(&s,4,550,payload,sizeof(payload))==112 && payload[6]==0xa2 && !payload[38] && !payload[40]);check_tm2(&s);
    f=frame(0xa3,0,0,40);assert(aps_accept_decoded(&s,&f,APS_ADC_NORMAL,600)==AP_OK);
    ack(reply,&s,0x23,UINT64_C(800000000),UINT64_C(1000000000),-4);
    assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,reply,sizeof(reply))==AP_EREMOTE && !s.transaction.pending);
    assert(s.applied_commands==3 && s.failed_transactions==1);
    assert(atm_pack(&s,5,650,payload,sizeof(payload))==112 && payload[55]==0xa3 && payload[75]==0xfc);
    check_tm2(&s);assert(aps_telemetry_format(&s,650,text,sizeof(text))>0 && strstr(text,"a_rc=-4"));
    s.last_decoded.command.version=0x80;assert(atm_pack(&s,5,650,payload,sizeof(payload))==AP_EARG);
    s.last_decoded.command.version=0xa3;s.last_decoded.command.rx_mhz=1;
    assert(atm_pack(&s,5,650,payload,sizeof(payload))==AP_EARG);
    s.last_decoded.command.version=0x81;s.last_decoded.command.rx_mhz=99;s.last_decoded.command.tx_mhz=100;
    assert(atm_pack(&s,5,650,payload,sizeof(payload))==AP_EARG);
    /* Mixed legacy/new snapshots identify each record independently. */
    s.last_decoded.command.version=1;s.last_decoded.command.rx_mhz=70;s.last_decoded.command.tx_mhz=6000;
    assert(atm_pack(&s,5,650,payload,sizeof(payload))==112 && payload[6]==1 && payload[55]==0xa3);check_tm2(&s);
    assert(aps_telemetry_format(&s,650,text,4)==AP_ELENGTH && !text[0]);
    puts("PASS kHz PS: exact UDP Hz, text/binary ACK routing, adjacent rejection, ATM2 versions/raw, TM2 CRC and failure records; native only");
    return 0;
}
