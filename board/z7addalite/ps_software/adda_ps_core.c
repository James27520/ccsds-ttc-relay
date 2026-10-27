#include "adda_ps_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *origin_name(enum aps_origin origin)
{
    switch(origin) {
    case APS_ADC_NORMAL:return "ADC_NORMAL";
    case APS_ADC_TEST:return "ADC_TEST";
    case APS_SYNTHETIC:return "SYNTHETIC";
    case APS_UART_NETTEST:return "UART_NETTEST";
    default:return "UNKNOWN";
    }
}
static void emit(struct aps_state *s,const char *text) { if(s->io.log)s->io.log(s->io.context,text); }
static void trace_command(struct aps_state *s,const char *event,enum aps_origin origin,
                          const struct ap_command *command,int rc)
{
    char text[160];
    (void)snprintf(text,sizeof(text),"%s source=%s rx=%u tx=%u air_seq=%u rc=%d\r\n",event,
                   origin_name(origin),(unsigned)command->rx_mhz,(unsigned)command->tx_mhz,
                   (unsigned)command->seq,rc);
    emit(s,text);
}
void aps_init(struct aps_state *state,const struct aps_io *io)
{
    if(!state)return;
    memset(state,0,sizeof(*state));
    if(io)state->io=*io;
    ap_transaction_init(&state->transaction,1u);
    state->rx_gain_db=0u;state->tx_attenuation_db=89u;
    emit(state,"ADDA PS control core: network=OFF armed=OFF; selftest is local only\r\n");
}
void aps_set_network_ready(struct aps_state *state,unsigned ready)
{
    if(!state)return;
    state->network_ready=ready?1u:0u;
    if(!ready && state->transaction.pending) {
        ap_transaction_abort(&state->transaction);++state->failed_transactions;
        emit(state,"NETWORK_LOST pending aborted; remote state not confirmed\r\n");
    }
}
static void send_attempt(struct aps_state *s,uint32_t now)
{
    int rc;
    if(!s->network_ready || !s->transaction.pending || !s->io.udp_send)return;
    ++s->sends;s->last_send_ms=now;
    rc=s->io.udp_send(s->io.context,APS_RELAY_IPV4,APS_RELAY_PORT,s->transaction.packet,AP_RF_BYTES);
    trace_command(s,"UDP_SEND_ATTEMPT",s->pending_origin,&s->transaction.pending_command,rc);
}
static int begin_command(struct aps_state *s,const struct ap_command *command,
                         enum aps_origin origin,uint8_t gain,uint8_t attenuation,uint32_t now)
{
    int rc;
    if(!s->network_ready || !s->io.udp_send) {emit(s,"NETWORK_NOT_READY\r\n");return AP_EBUSY;}
    rc=ap_transaction_begin(&s->transaction,command,gain,attenuation);
    trace_command(s,"COMMAND",origin,command,rc);
    if(rc==AP_OK) {s->pending_origin=origin;s->sends=0u;send_attempt(s,now);}
    return rc;
}
int aps_accept_decoded(struct aps_state *s,const struct ap_frame_result *frame,
                        enum aps_origin origin,uint32_t now)
{
    struct ap_command command;
    int rc;
    if(!s || !frame)return AP_EARG;
    rc=ap_body_parse(frame->body,AP_BODY_BYTES,&command);
    if(rc!=AP_OK)return rc;
    ++s->decoded_frames;
    trace_command(s,"DECODED",origin,&command,AP_OK);
    if(origin!=APS_ADC_NORMAL) {emit(s,"LOCAL_ONLY provenance excludes RF_SET\r\n");return AP_OK;}
    if(!s->armed) {emit(s,"LOCAL_ONLY forwarding is disarmed\r\n");return AP_OK;}
    return begin_command(s,&command,origin,s->rx_gain_db,s->tx_attenuation_db,now);
}
int aps_decode_samples(struct aps_state *s,const int16_t *samples,size_t count,
                        enum aps_origin origin,unsigned metadata_validated,
                        uint32_t now,adda_demod_stats *stats)
{
    struct ap_frame_result frame;
    int rc;
    if(!s || !samples || !stats)return AP_EARG;
    if(origin!=APS_ADC_NORMAL && origin!=APS_ADC_TEST && origin!=APS_SYNTHETIC)return AP_EARG;
    if(!metadata_validated) {emit(s,"CAPTURE_REJECT metadata not validated\r\n");return AP_EARG;}
    rc=adda_receive(samples,count,&frame,stats);
    if(rc==1)return aps_accept_decoded(s,&frame,origin,now);
    emit(s,rc==0?"DECODE_NO_VALID_FRAME\r\n":"DECODE_ERROR\r\n");
    return rc==0?AP_ENOFRAME:AP_EARG;
}
void aps_poll(struct aps_state *s,uint32_t now)
{
    if(!s || !s->transaction.pending)return;
    if(!s->network_ready || !s->io.udp_send) {aps_set_network_ready(s,0u);return;}
    if((uint32_t)(now-s->last_send_ms)<APS_RETRY_MS)return;
    if(s->sends>=APS_MAX_SENDS) {
        ap_transaction_abort(&s->transaction);++s->failed_transactions;
        emit(s,"ACK_TIMEOUT not marked applied; remote state not confirmed\r\n");return;
    }
    send_attempt(s,now);
}
int aps_udp_received(struct aps_state *s,uint32_t peer,uint16_t port,const uint8_t *bytes,size_t length)
{
    struct ap_ack ack;
    struct ap_command command;
    int rc;
    if(!s || !bytes)return AP_EARG;
    if(peer!=APS_RELAY_IPV4 || port!=APS_RELAY_PORT)return AP_EACK;
    rc=ap_ack_parse(bytes,length,&ack);
    if(rc!=AP_OK)return rc;
    command=s->transaction.pending_command;
    rc=ap_transaction_ack(&s->transaction,&ack,10000u);
    trace_command(s,"ACK",s->pending_origin,&command,rc);
    if(rc==AP_OK)++s->applied_commands;
    /* Negative rc ACK is observable and remains pending for the bounded retry
     * policy. A later valid matched ACK is still allowed before exhaustion. */
    return rc;
}
int aps_selftest(struct aps_state *s)
{
    static const uint8_t cadu[3][20]={
      {0x1a,0xcf,0xfc,0x1d,0xbc,0xd9,0x01,0x4c,0x82,0xbf,0x4b,0x2c,0x0b,0x38,0x94,0xc1,0x0d,0xdf,0xdc,0x50},
      {0x1a,0xcf,0xfc,0x1d,0xbc,0xd9,0x02,0xe4,0x25,0xbf,0x71,0x78,0xa9,0x26,0x46,0x02,0x7b,0x43,0x4d,0x99},
      {0x1a,0xcf,0xfc,0x1d,0xbc,0xd9,0x01,0x78,0x79,0x6f,0xe8,0x9c,0x0b,0x38,0x94,0xfb,0x87,0x71,0xde,0x0a}};
    static const uint16_t rx[3]={100u,120u,2400u},tx[3]={2450u,1000u,2450u};
    static const uint8_t seq[3]={0u,1u,7u};
    uint8_t bits[AP_FRAME_BITS];struct ap_frame_result frame;
    unsigned v,i;
    if(!s)return AP_EARG;
    for(v=0;v<3u;++v) {
        for(i=0;i<AP_FRAME_BITS;++i)bits[i]=(uint8_t)(((unsigned)cadu[v][i/8u]>>(7u-i%8u))&1u);
        if(ap_find_frame(bits,AP_FRAME_BITS,0u,&frame)!=AP_OK || frame.command.rx_mhz!=rx[v] ||
           frame.command.tx_mhz!=tx[v] || frame.command.seq!=seq[v]) {
            emit(s,"SELFTEST_FAIL source=SYNTHETIC no UDP attempted\r\n");return AP_ECRC;
        }
    }
    emit(s,"SELFTEST_PASS 3 external digital-frame vectors source=SYNTHETIC no UDP attempted\r\n");
    return AP_OK;
}
static int parse_uint(const char *text,unsigned limit,unsigned *value)
{
    unsigned result=0u,digit;
    if(!text || !*text)return 0;
    while(*text) {
        if(*text<'0'||*text>'9')return 0;
        digit=(unsigned)(*text-'0');
        if(result>limit/10u || (result==limit/10u && digit>limit%10u))return 0;
        result=result*10u+digit;++text;
    }
    *value=result;return 1;
}
int aps_command_line(struct aps_state *s,const char *line,uint32_t now)
{
    char copy[128],status[180],*args[7],*p;
    unsigned argc=0u,rx,tx,seq,gain,atten;
    size_t n=0u;
    struct ap_command command;
    if(!s||!line)return AP_EARG;
    while(n<sizeof(copy) && line[n])++n;
    if(n==sizeof(copy))return AP_ELENGTH;
    memcpy(copy,line,n+1u);p=copy;
    while(*p) {
        while(*p==' '||*p=='\t')++p;
        if(!*p)break;
        if(argc>=7u)return AP_EARG;
        args[argc++]=p;
        while(*p && *p!=' ' && *p!='\t')++p;
        if(*p)*p++=0;
    }
    if(argc==1u && !strcmp(args[0],"help")) {
        emit(s,"status | selftest | arm on/off | levels GAIN ATT | nettest RX_MHz TX_MHz SEQ GAIN ATT\r\n");
        return AP_OK;
    }
    if(argc==1u && !strcmp(args[0],"status")) {
        (void)snprintf(status,sizeof(status),"STATUS network=%u armed=%u decoded=%u applied=%u pending=%u retries=%u failures=%u gain=%u att=%u\r\n",
            s->network_ready,s->armed,s->decoded_frames,s->applied_commands,s->transaction.pending,s->sends,
            s->failed_transactions,(unsigned)s->rx_gain_db,(unsigned)s->tx_attenuation_db);
        emit(s,status);return AP_OK;
    }
    if(argc==1u && !strcmp(args[0],"selftest"))return aps_selftest(s);
    if(argc==2u && !strcmp(args[0],"arm")) {
        if(!strcmp(args[1],"on")) {s->armed=1u;emit(s,"ARMED only validated ADC_NORMAL may forward\r\n");return AP_OK;}
        if(!strcmp(args[1],"off")) {
            s->armed=0u;
            if(s->transaction.pending) {ap_transaction_abort(&s->transaction);emit(s,"ABORT pending; remote state not confirmed\r\n");}
            emit(s,"DISARMED\r\n");return AP_OK;
        }
    }
    if(argc==3u && !strcmp(args[0],"levels") && parse_uint(args[1],76u,&gain) && parse_uint(args[2],89u,&atten)) {
        s->rx_gain_db=(uint8_t)gain;s->tx_attenuation_db=(uint8_t)atten;
        emit(s,"LEVELS_STAGED only; no RF_SET sent\r\n");return AP_OK;
    }
    if(argc==6u && !strcmp(args[0],"nettest") && parse_uint(args[1],6000u,&rx) &&
       parse_uint(args[2],6000u,&tx) && parse_uint(args[3],255u,&seq) &&
       parse_uint(args[4],76u,&gain) && parse_uint(args[5],89u,&atten)) {
        command.version=1u;command.rx_mhz=(uint16_t)rx;command.tx_mhz=(uint16_t)tx;command.seq=(uint8_t)seq;
        return begin_command(s,&command,APS_UART_NETTEST,(uint8_t)gain,(uint8_t)atten,now);
    }
    emit(s,"COMMAND_REJECT invalid syntax/range\r\n");return AP_EARG;
}
