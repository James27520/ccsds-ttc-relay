#include "adda_ps_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned checks=0u;
#define CHECK(x) do { ++checks;if(!(x)){fprintf(stderr,"FAIL line%d %s\n",__LINE__,#x);exit(1);} }while(0)
struct fake_io { unsigned sends; unsigned logs; uint8_t packet[26]; };
static void fake_log(void *context,const char *text)
{
    struct fake_io *io=context;++io->logs;
    CHECK(text!=NULL);
}
static int fake_send(void *context,uint32_t ip,uint16_t port,const uint8_t *bytes,size_t size)
{
    struct fake_io *io=context;
    CHECK(ip==APS_RELAY_IPV4 && port==5005u && size==26u);
    memcpy(io->packet,bytes,26u);++io->sends;return 0;
}
static void make_frame(struct ap_frame_result *frame,uint16_t rx,uint16_t tx,uint8_t seq)
{
    struct ap_command command={1u,rx,tx,seq};uint8_t bits[160];
    CHECK(ap_frame_encode(&command,bits)==AP_OK);
    CHECK(ap_find_frame(bits,160u,0u,frame)==AP_OK);
}
int main(void)
{
    struct fake_io fake={0u,0u,{0}};
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
    puts("PS_CORE_PASS startup quiet, source gating, explicit nettest, ACK-only apply, bounded exact retries, millis wrap, disconnect and strict CLI");
    printf("PASS %u assertions; UDP/UART callbacks are mocks, no hardware or network\n",checks);
    return 0;
}
