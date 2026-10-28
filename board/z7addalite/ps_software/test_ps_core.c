#include "adda_ps_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned checks=0u;
#define CHECK(x) do { ++checks;if(!(x)){fprintf(stderr,"FAIL line%d %s\n",__LINE__,#x);exit(1);} }while(0)
struct fake_io {
    unsigned sends,logs;uint8_t packet[26];
    int send_rc;char last_log[APS_TM1_MAX_BYTES];
};
static void fake_log(void *context,const char *text)
{
    struct fake_io *io=context;++io->logs;
    CHECK(text!=NULL);
    CHECK(strlen(text)<sizeof(io->last_log));
    strcpy(io->last_log,text);
}
static int fake_send(void *context,uint32_t ip,uint16_t port,const uint8_t *bytes,size_t size)
{
    struct fake_io *io=context;
    CHECK(ip==APS_RELAY_IPV4 && port==5005u && size==26u);
    memcpy(io->packet,bytes,26u);++io->sends;return io->send_rc;
}
static void make_frame(struct ap_frame_result *frame,uint16_t rx,uint16_t tx,uint8_t seq)
{
    struct ap_command command={1u,rx,tx,seq};uint8_t bits[160];
    CHECK(ap_frame_encode(&command,bits)==AP_OK);
    CHECK(ap_find_frame(bits,160u,0u,frame)==AP_OK);
}
static void check_tm1(const char *line)
{
    const char *tail=strstr(line," crc16=");unsigned crc=0u;
    CHECK(strncmp(line,"TM1 ",4u)==0 && tail!=NULL);
    CHECK(sscanf(tail," crc16=%4X",&crc)==1);
    CHECK(strlen(tail)==13u && tail[11]=='\r' && tail[12]=='\n');
    CHECK(strchr(line,'\n')==line+strlen(line)-1u);
    CHECK(strchr(line,'\r')==line+strlen(line)-2u);
    CHECK(ap_crc16((const uint8_t *)line,(size_t)(tail-line))==crc);
}
static void telemetry_tests(void)
{
    struct fake_io fake={0};struct aps_io io={&fake,fake_log,fake_send};
    struct aps_state s,before;struct ap_frame_result frame;
    struct aps_ack_record saved_ack;struct aps_send_record saved_send;
    char line[APS_TM1_MAX_BYTES],tiny[8],ack[96];int n;uint16_t seq;
    aps_init(&s,&io);before=s;
    CHECK(aps_command_line(&s,"telemetry",123u)==AP_OK);
    CHECK(!memcmp(&s,&before,sizeof(s)) && fake.sends==0u);
    check_tm1(fake.last_log);
    CHECK(strstr(fake.last_log,"uptime_ms=123 events=0 network=0 armed=0 pending=0 decoded=0 applied=0 failures=0")!=NULL);
    CHECK(strstr(fake.last_log,"d_valid=0 d_event=0 d_origin=0 d_air_seq=0 d_rx_mhz=0 d_tx_mhz=0")!=NULL);
    CHECK(strstr(fake.last_log,"s_valid=0 s_event=0 s_origin=0")!=NULL);
    CHECK(strstr(fake.last_log,"a_valid=0 a_event=0 a_origin=0")!=NULL);
    CHECK(strstr(fake.last_log,"a_rx_hz=0 a_tx_hz=0 spi_valid=0")!=NULL);
    /* Independent binascii.crc_hqx(prefix, 0xffff) known-answer fixture:
     * the fresh TM1 prefix above is exactly 360 ASCII bytes. */
    CHECK(strlen(fake.last_log)==373u && !strcmp(fake.last_log+360u," crc16=F8E2\r\n"));
    CHECK(aps_telemetry_format(NULL,0u,line,sizeof(line))==AP_EARG);
    CHECK(aps_telemetry_format(&s,0u,NULL,sizeof(line))==AP_EARG);
    CHECK(aps_telemetry_format(&s,0u,line,0u)==AP_EARG);
    CHECK(aps_telemetry_format(&s,0u,tiny,sizeof(tiny))==AP_ELENGTH && tiny[0]==0);
    n=aps_telemetry_format(&s,123u,line,sizeof(line));CHECK(n>0);
    CHECK((size_t)n==strlen(line) && !strcmp(line,fake.last_log));
    CHECK(aps_telemetry_format(&s,123u,line,(size_t)n)==AP_ELENGTH && line[0]==0);
    CHECK(aps_telemetry_format(&s,123u,line,(size_t)n+1u)==n);check_tm1(line);
    CHECK(aps_command_line(&s,"telemetry trailing",1u)==AP_EARG);
    CHECK(!memcmp(&s,&before,sizeof(s)));

    make_frame(&frame,901u,1001u,82u);
    CHECK(aps_accept_decoded(&s,&frame,APS_ADC_NORMAL,10u)==AP_OK);
    CHECK(s.last_decoded.valid && s.last_decoded.origin==APS_ADC_NORMAL);
    CHECK(s.last_decoded.command.seq==82u && s.last_decoded.command.rx_mhz==901u);
    CHECK(s.telemetry_events==1u && !s.last_send.record.valid && !s.last_ack.record.valid);
    before=s;frame.body[7]^=1u;
    CHECK(aps_accept_decoded(&s,&frame,APS_ADC_NORMAL,11u)==AP_ECRC);
    CHECK(!memcmp(&s,&before,sizeof(s)));frame.body[7]^=1u;
    aps_set_network_ready(&s,1u);
    fake.send_rc=-2;
    CHECK(aps_command_line(&s,"nettest 900 1000 80 0 89",20u)==AP_OK);
    CHECK(s.last_send.record.origin==APS_UART_NETTEST && s.last_send.rc==-2);
    CHECK(s.last_send.count==1u && s.last_send.record.command.seq==80u);
    CHECK(!s.last_ack.record.valid && !s.applied_commands && s.transaction.pending);
    seq=s.transaction.pending_transaction_seq;
    fake.send_rc=0;aps_poll(&s,270u);
    CHECK(s.last_send.count==2u && s.last_send.rc==0 && s.last_send.transaction_seq==seq);
    CHECK(s.telemetry_events==3u && !s.last_ack.record.valid);

    n=snprintf(ack,sizeof(ack),"rc=0 seq=%u rx_hz=899999998 tx_hz=1000000002\n",(unsigned)seq);
    CHECK(aps_udp_received(&s,APS_RELAY_IPV4^1u,APS_RELAY_PORT,(uint8_t *)ack,(size_t)n)==AP_EACK);
    CHECK(aps_udp_received(&s,APS_RELAY_IPV4,APS_RELAY_PORT+1u,(uint8_t *)ack,(size_t)n)==AP_EACK);
    CHECK(aps_udp_received(&s,APS_RELAY_IPV4,APS_RELAY_PORT,(uint8_t *)"bad",3u)==AP_EACK);
    CHECK(!s.last_ack.record.valid && s.telemetry_events==3u);
    CHECK(aps_udp_received(&s,APS_RELAY_IPV4,APS_RELAY_PORT,(uint8_t *)ack,(size_t)n)==AP_OK);
    CHECK(s.last_ack.record.valid && s.last_ack.record.origin==APS_UART_NETTEST);
    CHECK(s.last_ack.reply.rx_hz==UINT64_C(899999998) && s.last_ack.reply.tx_hz==UINT64_C(1000000002));
    CHECK(s.last_ack.reply.seq==seq && s.last_ack.record.command.rx_mhz==900u);
    CHECK(s.last_ack.record.event==4u && s.telemetry_events==4u && s.applied_commands==1u);
    saved_ack=s.last_ack;saved_send=s.last_send;
    /* A later local decode owns separate provenance and cannot relabel ACK/send. */
    CHECK(aps_accept_decoded(&s,&frame,APS_ADC_TEST,300u)==AP_OK);
    CHECK(s.last_decoded.origin==APS_ADC_TEST && s.last_decoded.command.seq==82u);
    CHECK(!memcmp(&s.last_ack,&saved_ack,sizeof(saved_ack)));
    CHECK(!memcmp(&s.last_send,&saved_send,sizeof(saved_send)));
    before=s;CHECK(aps_command_line(&s,"telemetry",301u)==AP_OK);
    CHECK(!memcmp(&s,&before,sizeof(s)));check_tm1(fake.last_log);
    CHECK(strstr(fake.last_log,"d_origin=2 d_air_seq=82 d_rx_mhz=901 d_tx_mhz=1001")!=NULL);
    CHECK(strstr(fake.last_log,"s_origin=4 s_air_seq=80 s_rx_mhz=900 s_tx_mhz=1000")!=NULL);
    CHECK(strstr(fake.last_log,"a_origin=4 a_air_seq=80 a_rx_mhz=900 a_tx_mhz=1000")!=NULL);
    CHECK(strstr(fake.last_log,"a_rx_hz=899999998 a_tx_hz=1000000002 spi_valid=0")!=NULL);

    CHECK(aps_command_line(&s,"nettest 901 1000 81 0 89",400u)==AP_OK);
    seq=s.transaction.pending_transaction_seq;
    n=snprintf(ack,sizeof(ack),"rc=-1 seq=%u rx_hz=901000000 tx_hz=1000000000\n",(unsigned)seq);
    CHECK(aps_udp_received(&s,APS_RELAY_IPV4,APS_RELAY_PORT,(uint8_t *)ack,(size_t)n)==AP_EREMOTE);
    n=snprintf(ack,sizeof(ack),"rc=0 seq=%u rx_hz=902000000 tx_hz=1000000000\n",(unsigned)seq);
    CHECK(aps_udp_received(&s,APS_RELAY_IPV4,APS_RELAY_PORT,(uint8_t *)ack,(size_t)n)==AP_EMISMATCH);
    n=snprintf(ack,sizeof(ack),"rc=0 seq=%u rx_hz=901000000 tx_hz=1000000000\n",(unsigned)(seq+1u));
    CHECK(aps_udp_received(&s,APS_RELAY_IPV4,APS_RELAY_PORT,(uint8_t *)ack,(size_t)n)==AP_ESTALE);
    CHECK(!memcmp(&s.last_ack,&saved_ack,sizeof(saved_ack)) && s.applied_commands==1u);
    aps_set_network_ready(&s,0u);before=s;
    CHECK(aps_command_line(&s,"telemetry",UINT32_MAX)==AP_OK);
    CHECK(!memcmp(&s,&before,sizeof(s)) && !s.transaction.pending && s.failed_transactions==1u);
    CHECK(strstr(fake.last_log,"uptime_ms=4294967295")!=NULL);check_tm1(fake.last_log);
    CHECK(!memcmp(&s.last_ack,&saved_ack,sizeof(saved_ack)));
    /* Event zero after unsigned wrap is still a valid event. */
    s.telemetry_events=UINT32_MAX;
    CHECK(aps_accept_decoded(&s,&frame,APS_SYNTHETIC,0u)==AP_OK);
    CHECK(s.last_decoded.valid && s.last_decoded.event==0u && s.telemetry_events==0u);
    before=s;CHECK(aps_command_line(&s,"telemetry",0u)==AP_OK);
    CHECK(!memcmp(&s,&before,sizeof(s)));check_tm1(fake.last_log);
    /* Declared line bound also covers full-width counters and ACK integers. */
    s.last_ack.reply.rx_hz=UINT64_MAX;s.last_ack.reply.tx_hz=UINT64_MAX;
    s.last_ack.reply.rc=INT32_MIN;s.last_send.rc=INT32_MIN;
    s.last_send.count=UINT32_MAX;s.telemetry_events=UINT32_MAX;
    s.decoded_frames=UINT32_MAX;s.applied_commands=UINT32_MAX;s.failed_transactions=UINT32_MAX;
    n=aps_telemetry_format(&s,UINT32_MAX,line,sizeof(line));
    CHECK(n>0 && (size_t)n<APS_TM1_MAX_BYTES);check_tm1(line);
    CHECK(strstr(line,"a_rx_hz=18446744073709551615 a_tx_hz=18446744073709551615")!=NULL);
    aps_init(&s,&io);
    CHECK(!s.last_decoded.valid && !s.last_send.record.valid && !s.last_ack.record.valid);
}
int main(void)
{
    struct fake_io fake={0};
    struct aps_io io={&fake,fake_log,fake_send};
    struct aps_state state;
    struct ap_frame_result frame;
    uint8_t first_packet[26];
    char ack[96];
    int count;
    unsigned initial;
    adda_demod_stats stats;
    int16_t placeholder=0;
    aps_init(&state,&io);
    CHECK(fake.sends==0u && state.network_ready==0u && state.armed==0u);
    CHECK(aps_command_line(&state,"selftest",0u)==AP_OK && fake.sends==0u);
    CHECK(aps_command_line(&state,"status",0u)==AP_OK && fake.sends==0u);
    CHECK(aps_command_line(&state,"nettest 100 2450 0 0 89",0u)==AP_EBUSY && fake.sends==0u);
    aps_set_network_ready(&state,1u);
    make_frame(&frame,100u,2450u,0u);
    CHECK(aps_accept_decoded(&state,&frame,APS_ADC_NORMAL,10u)==AP_OK && fake.sends==0u);
    CHECK(aps_command_line(&state,"arm on",10u)==AP_OK);
    CHECK(aps_command_line(&state,"selftest",10u)==AP_OK && fake.sends==0u);
    CHECK(aps_accept_decoded(&state,&frame,APS_SYNTHETIC,10u)==AP_OK && fake.sends==0u);
    CHECK(aps_accept_decoded(&state,&frame,APS_ADC_TEST,10u)==AP_OK && fake.sends==0u);
    CHECK(aps_accept_decoded(&state,&frame,APS_UART_NETTEST,10u)==AP_OK && fake.sends==0u);
    CHECK(aps_decode_samples(&state,&placeholder,1u,APS_ADC_NORMAL,0u,10u,&stats)==AP_EARG && fake.sends==0u);
    CHECK(aps_accept_decoded(&state,&frame,APS_ADC_NORMAL,10u)==AP_OK && fake.sends==1u);
    CHECK(!state.applied_commands && state.transaction.pending);
    memcpy(first_packet,fake.packet,26u);
    CHECK(aps_accept_decoded(&state,&frame,APS_ADC_NORMAL,20u)==AP_PENDING && fake.sends==1u);
    count=snprintf(ack,sizeof(ack),"rc=0 seq=%u rx_hz=100000000 tx_hz=2450000000\n",state.transaction.pending_transaction_seq);
    CHECK(aps_udp_received(&state,APS_RELAY_IPV4^1u,5005u,(uint8_t*)ack,(size_t)count)==AP_EACK);
    CHECK(aps_udp_received(&state,APS_RELAY_IPV4,5006u,(uint8_t*)ack,(size_t)count)==AP_EACK);
    CHECK(!state.applied_commands);
    aps_poll(&state,260u);CHECK(fake.sends==2u && !memcmp(fake.packet,first_packet,26u));
    CHECK(aps_udp_received(&state,APS_RELAY_IPV4,5005u,(uint8_t*)ack,(size_t)count)==AP_OK);
    CHECK(state.applied_commands==1u && !state.transaction.pending);
    CHECK(aps_accept_decoded(&state,&frame,APS_ADC_NORMAL,270u)==AP_DUPLICATE && fake.sends==2u);
    frame.body[7]^=1u;
    CHECK(aps_accept_decoded(&state,&frame,APS_ADC_NORMAL,280u)==AP_ECRC && fake.sends==2u);
    CHECK(aps_command_line(&state,"arm off",300u)==AP_OK && !state.armed);
    CHECK(aps_command_line(&state,"levels 76 89",300u)==AP_OK && fake.sends==2u);
    CHECK(aps_command_line(&state,"levels 77 89",300u)==AP_EARG);
    CHECK(aps_command_line(&state,"nettest 69 2450 1 0 89",300u)==AP_ERANGE);
    CHECK(aps_command_line(&state,"nettest -1 2450 1 0 89",300u)==AP_EARG);
    CHECK(aps_command_line(&state,"nettest 100 2450 256 0 89",300u)==AP_EARG);
    CHECK(aps_command_line(&state,"nettest 100 2450 1 0 90",300u)==AP_EARG);
    CHECK(aps_command_line(&state,"nettest 100 2450 1 0 89 trailing",300u)==AP_EARG);
    CHECK(aps_command_line(&state,"nettest 100 2450 1 0 89",UINT32_MAX-20u)==AP_OK);
    CHECK(fake.sends==3u && state.pending_origin==APS_UART_NETTEST);
    aps_poll(&state,229u);CHECK(fake.sends==4u); /* millis wrap */
    aps_poll(&state,479u);CHECK(fake.sends==5u);
    aps_poll(&state,729u);CHECK(fake.sends==5u && !state.transaction.pending);
    CHECK(state.applied_commands==1u && state.failed_transactions==1u);
    CHECK(aps_command_line(&state,"nettest 120 1000 2 0 89",800u)==AP_OK);
    initial=fake.sends;aps_set_network_ready(&state,0u);aps_poll(&state,2000u);
    CHECK(!state.transaction.pending && fake.sends==initial && state.applied_commands==1u);
    CHECK(aps_command_line(&state,"selftest",2000u)==AP_OK && fake.sends==initial);
    telemetry_tests();
    puts("PS_CORE_PASS startup quiet, source gating, explicit nettest, ACK-only apply, bounded exact retries, millis wrap, disconnect and strict CLI");
    printf("PASS %u assertions; UDP/UART callbacks are mocks, no hardware or network\n",checks);
    return 0;
}
