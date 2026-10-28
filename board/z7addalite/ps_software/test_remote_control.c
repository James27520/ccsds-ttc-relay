/* Pure native protocol/core/ATM2 checks. No sockets, MMIO or board access. */
#include "adda_telemetry_tx.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static unsigned sends;static uint8_t sent[34];
static char last_log[512];
static void log_text(void *c,const char *text){(void)c;assert(strlen(text)<sizeof(last_log));strcpy(last_log,text);}
static int send_udp(void *c,uint32_t peer,uint16_t port,const uint8_t *p,size_t n)
{(void)c;assert(peer==APS_RELAY_IPV4 && port==5005 && n==34);memcpy(sent,p,n);++sends;return 0;}
static void p32(uint8_t *p,uint32_t v){p[0]=(uint8_t)(v>>24);p[1]=(uint8_t)(v>>16);p[2]=(uint8_t)(v>>8);p[3]=(uint8_t)v;}
static void p64(uint8_t *p,uint64_t v){p32(p,(uint32_t)(v>>32));p32(p+4,(uint32_t)v);}
static void crc(uint8_t *p){uint16_t c=ap_crc16(p,48);p[48]=(uint8_t)(c>>8);p[49]=(uint8_t)c;}
static void ack(uint8_t *p,const struct aps_state *s,uint8_t op,int rc)
{
    memset(p,0,50);p[0]=2;p[1]=0x20;p[2]=(uint8_t)(0xc0u|(s->transaction.pending_transaction_seq>>8));
    p[3]=(uint8_t)s->transaction.pending_transaction_seq;p[5]=43;p[6]=1;p[7]=op;p[8]=1;p[9]=2;
    p32(p+12,89000);p32(p+16,89000);p32(p+24,12345);
    p64(p+28,UINT64_C(900000000));p64(p+36,UINT64_C(1001000000));p32(p+44,(uint32_t)rc);crc(p);
}
static struct ap_frame_result frame(uint8_t op,uint8_t seq)
{
    struct ap_frame_result f;memset(&f,0,sizeof(f));f.command.version=op;f.command.seq=seq;
    f.command.rx_mhz=900;f.command.tx_mhz=1001;assert(ap_body_build(&f.command,f.body)==0);return f;
}
int main(void)
{
    struct aps_state s;struct aps_io io={0,log_text,send_udp};struct ap_frame_result f,found;
    struct ap_ack a;struct ap_relay_status r;struct ap_transaction t;
    uint8_t p[50],bits[160],burst[484],payload[112];unsigned op,before;
    for(op=0x21;op<=0x23;++op){f=frame((uint8_t)op,9);assert(ap_frame_encode(&f.command,bits)==0);
      assert(ap_find_frame(bits,160,0,&found)==0 && found.command.version==op);
      assert(ap_control_packet(&f.command,0x1234,p,sizeof(p))==0);
      assert(p[0]==1 && p[1]==0x20 && p[2]==0xd2 && p[3]==0x34 && p[5]==27 && p[6]==1 && p[7]==op);
      assert(p[8]==(op==0x21?1:0) && p[9]==(op==0x21?30:0) && p[10]==(op==0x21?50:0));
      assert(p[12]==0 && p[13]==(op==0x21?4:0) && p[14]==(op==0x21?0x93:0) && p[15]==(op==0x21?0xe0:0));
    }
    aps_init(&s,&io);s.network_ready=s.armed=1;f=frame(0x21,1);
    assert(aps_accept_decoded(&s,&f,APS_SYNTHETIC,0)==0 && sends==0);
    assert(aps_accept_decoded(&s,&f,APS_ADC_NORMAL,0)==0 && sends==1 && s.transaction.packet_length==34);
    assert(sent[7]==0x21);aps_poll(&s,250);assert(sends==2 && !memcmp(sent,s.transaction.packet,34));
    ack(p,&s,0x22,0);assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,p,50)==AP_EACK);
    ack(p,&s,0x21,0);p[8]=3;p[9]=1;p[10]=p[11]=30;p32(p+12,50000);p32(p+16,50000);p32(p+20,299999);crc(p);
    assert(aps_udp_received(&s,APS_RELAY_IPV4+1,5005,p,50)==AP_EACK);
    p[49]^=1;assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,p,50)==AP_ECRC);p[49]^=1;
    assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,p,49)==AP_ELENGTH);
    p[8]=1;crc(p);assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,p,50)==AP_EMISMATCH && s.transaction.pending);
    p[8]=7;crc(p);assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,p,50)==0 && s.applied_commands==1); /* past expiry is sticky */
    assert(atm_pack(&s,7,500,payload,112)==112 && !memcmp(payload,"ATM2",4));
    assert(payload[6]==0x21 && payload[7]==0x21 && payload[55]==0x21 && payload[92]==1 && payload[93]==30 && payload[95]==7);
    assert(atm_burst(&s,7,500,burst,sizeof(burst))==484 && burst[10]==112);
    assert(!memcmp(burst+8,burst+125,117) && !memcmp(burst+8,burst+359,117));
    before=sends;assert(aps_accept_decoded(&s,&f,APS_ADC_NORMAL,500)==AP_DUPLICATE && sends==before);
    f=frame(0x22,1);assert(aps_accept_decoded(&s,&f,APS_ADC_NORMAL,500)==AP_ECONFLICT); /* operation included */
    f=frame(0x22,2);assert(aps_accept_decoded(&s,&f,APS_ADC_NORMAL,500)==0);
    ack(p,&s,0x22,0);p64(p+28,UINT64_C(800000000));crc(p); /* stop never retunes/checks requested LO */
    assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,p,50)==0 && s.applied_commands==2);
    f=frame(0x23,3);assert(aps_accept_decoded(&s,&f,APS_ADC_NORMAL,600)==0);
    ack(p,&s,0x23,-4);assert(ap_control_ack_parse(p,50,&a,&r)==0 && a.rc==-4 && r.uptime_ms==12345);
    assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,p,50)==AP_EREMOTE && !s.transaction.pending && s.applied_commands==2 && s.failed_transactions==1);
    assert(s.last_ack.record.command.version==0x23 && s.last_ack.reply.rc==-4);
    assert(atm_pack(&s,8,600,payload,112)==112 && payload[55]==0x23 && payload[75]==0xfc && payload[95]==1);
    ap_transaction_init(&t,16383);f=frame(0x23,7);assert(ap_transaction_begin(&t,&f.command,0,89)==0);
    assert(ap_transaction_begin(&t,&f.command,0,89)==AP_PENDING);ap_transaction_abort(&t);
    f.command.seq=8;assert(ap_transaction_begin(&t,&f.command,0,89)==AP_ERANGE && !t.pending && t.next_transaction_seq==16384);
    ap_transaction_init(&t,16384);assert(ap_transaction_begin(&t,&f.command,0,89)==AP_ERANGE);
    aps_init(&s,&io);before=sends;
    assert(aps_command_line(&s,"remotenettest enable 900 1001 8 2000",0)==AP_EBUSY && sends==before);
    s.network_ready=s.armed=1;
    assert(aps_command_line(&s,"remotenettest enable 900 1001 8 2000",0)==AP_EBUSY && sends==before);s.armed=0;
    assert(aps_command_line(&s,"remotenettest enable 900 1001 8 1999",0)==AP_ERANGE);
    assert(aps_command_line(&s,"remotenettest status 900 1001 8 2000",0)==AP_ERANGE);
    assert(aps_command_line(&s,"remotenettest enable 900 1001 8 2000",0)==0 && sends==before+1);
    assert(sent[12]==0 && sent[13]==0 && sent[14]==7 && sent[15]==0xd0 && sent[9]==30 && sent[10]==50);
    assert(s.pending_origin==APS_UART_NETTEST && !s.last_decoded.valid && !s.decoded_frames);
    ack(p,&s,0x21,0);p[8]=3;p[9]=1;p[10]=p[11]=30;p32(p+12,50000);p32(p+16,50000);p32(p+20,1990);crc(p);
    assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,p,50)==0);
    assert(strstr(last_log,"REMOTE_ACK source=UART_NETTEST operation=33") && strstr(last_log,"remaining_ms=1990"));
    assert(aps_command_line(&s,"remotenettest status 900 1001 9 0",20)==0);
    ack(p,&s,0x23,0);p64(p+28,UINT64_C(800000000));crc(p);
    assert(aps_udp_received(&s,APS_RELAY_IPV4,5005,p,50)==0 && s.last_ack.reply.rx_hz==UINT64_C(800000000));
    puts("PASS remote control: air operations, UDP wire, source/peer gating, exact retries, readback validation, failures, ATM2, sequence exhaustion; native only");return 0;
}
