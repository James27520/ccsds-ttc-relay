/* Cross-module native fixtures: actual ADDA sender + LDSDR wire codec +
 * actual ADDA receiver/core/ATM2. All hardware snapshots below are fakes. */
#include "adda_telemetry_tx.h"
#include "../../ldsdr/remote_control/relay_remote_packet.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static struct remote_command received;
static uint8_t transmitted[REMOTE_COMMAND_SIZE];
static int udp_send(void *context,uint32_t peer,uint16_t port,const uint8_t *p,size_t n)
{
    (void)context;
    assert(peer==APS_RELAY_IPV4 && port==APS_RELAY_PORT && n==REMOTE_COMMAND_SIZE);
    /* Deliberately use the independent LDSDR implementation to parse ADDA. */
    assert(remote_parse(p,n,&received)==0);
    memcpy(transmitted,p,n);return 0;
}
static void run_case(const char *name,uint8_t operation,unsigned air_seq,
                     uint64_t actual_rx,uint64_t actual_tx,int remote_rc,unsigned valid)
{
    struct aps_state state,before;struct aps_io io={0,0,udp_send};struct ap_frame_result frame;
    struct remote_snapshot hardware;struct ap_ack decoded_ack;struct ap_relay_status status;
    struct ap_transaction transaction_copy;
    uint8_t packet[AP_CONTROL_BYTES],reply[REMOTE_ACK_SIZE],payload[ATM2_PAYLOAD_BYTES];
    char tm1[APS_TM1_MAX_BYTES];unsigned i;int tm1_length,expected=remote_rc?AP_EREMOTE:AP_OK;
    memset(&frame,0,sizeof(frame));frame.command.version=operation;
    frame.command.seq=(uint8_t)air_seq;frame.command.rx_mhz=900;frame.command.tx_mhz=1001;
    assert(ap_body_build(&frame.command,frame.body)==AP_OK);
    aps_init(&state,&io);state.network_ready=state.armed=1;
    assert(aps_accept_decoded(&state,&frame,APS_ADC_NORMAL,1000)==AP_OK);
    /* Verify direct ap_control_packet is precisely the bytes the core sent. */
    assert(ap_control_packet(&frame.command,1,packet,sizeof(packet))==AP_OK);
    assert(!memcmp(packet,transmitted,sizeof(packet)));
    assert(received.op==operation && received.seq==1 && received.rx_hz==UINT64_C(900000000) &&
           received.tx_hz==UINT64_C(1001000000));
    assert(received.mode==(operation==REMOTE_ENABLE?1:0) &&
           received.gain==(operation==REMOTE_ENABLE?30:0) &&
           received.attenuation==(operation==REMOTE_ENABLE?50:0) &&
           received.lease_ms==(operation==REMOTE_ENABLE?300000u:0u));
    memset(&hardware,0,sizeof(hardware));hardware.flags=(uint8_t)(valid?REMOTE_VALID:0);
    hardware.mode=(uint8_t)(valid?2:0);hardware.rx_hz=actual_rx;hardware.tx_hz=actual_tx;
    hardware.uptime_ms=9000;hardware.rc=remote_rc;
    if(valid)hardware.attenuation[0]=hardware.attenuation[1]=89000;
    if(operation==REMOTE_ENABLE && !remote_rc){
        hardware.flags=REMOTE_VALID|REMOTE_ACTIVE|REMOTE_EXPIRED;
        hardware.mode=1;hardware.gain[0]=hardware.gain[1]=30;
        hardware.attenuation[0]=hardware.attenuation[1]=50000;hardware.remaining_ms=299990;
    }
    /* Deliberately use LDSDR's actual encoder, never a mirrored byte fixture. */
    remote_encode_ack(reply,received.seq,received.op,&hardware);
    assert(ap_control_ack_parse(reply,sizeof(reply),&decoded_ack,&status)==AP_OK);
    assert(decoded_ack.rc==remote_rc && decoded_ack.rx_hz==actual_rx && decoded_ack.tx_hz==actual_tx);
    assert(status.operation==operation && status.flags==hardware.flags && status.mode==hardware.mode &&
           status.rx1_gain==hardware.gain[0] && status.rx2_gain==hardware.gain[1] &&
           status.tx1_mdB==hardware.attenuation[0] && status.tx2_mdB==hardware.attenuation[1] &&
           status.remaining_ms==hardware.remaining_ms && status.uptime_ms==hardware.uptime_ms);
    transaction_copy=state.transaction;
    assert(ap_transaction_control_ack(&transaction_copy,&decoded_ack,&status,10000)==expected);
    assert(aps_udp_received(&state,APS_RELAY_IPV4,APS_RELAY_PORT,reply,sizeof(reply))==expected);
    assert(!state.transaction.pending && state.applied_commands==(remote_rc?0u:1u) &&
           state.failed_transactions==(remote_rc?1u:0u));
    assert(state.last_decoded.origin==APS_ADC_NORMAL && state.last_send.record.origin==APS_ADC_NORMAL &&
           state.last_ack.record.origin==APS_ADC_NORMAL && state.last_decoded.event<state.last_send.record.event &&
           state.last_send.record.event<state.last_ack.record.event);
    state.armed=0; /* Same post-ACK disarm used by the service before serialization. */
    before=state;tm1_length=aps_telemetry_format(&state,1100,tm1,sizeof(tm1));
    assert(tm1_length>2 && tm1[tm1_length-2]=='\r' && tm1[tm1_length-1]=='\n');
    assert(!memcmp(&state,&before,sizeof(state)));tm1[tm1_length-2]=0;
    if(remote_rc){
        assert(strstr(tm1," a_valid=0 a_event=0 a_origin=0 a_air_seq=0 a_rx_mhz=0 a_tx_mhz=0 a_udp_seq=0 a_rc=0 a_rx_hz=0 a_tx_hz=0 spi_valid=0"));
        assert(state.last_ack.record.valid && state.last_ack.reply.rc==remote_rc);
    }
    assert(atm_pack(&state,7,1100,payload,sizeof(payload))==ATM2_PAYLOAD_BYTES);
    printf("{\"case\":\"%s\",\"operation\":%u,\"air_seq\":%u,\"remote_rc\":%d,\"crc16\":%u,\"payload_hex\":\"",
           name,(unsigned)operation,air_seq,remote_rc,(unsigned)ap_crc16(payload,sizeof(payload)));
    for(i=0;i<sizeof(payload);++i)printf("%02x",payload[i]);
    printf("\",\"tm1\":\"%s\"}\n",tm1);
}
int main(void)
{
    run_case("enable",REMOTE_ENABLE,11,UINT64_C(900000123),UINT64_C(1001000456),0,1);
    run_case("status_different_lo",REMOTE_STATUS,12,UINT64_C(901000000),UINT64_C(1102000000),0,1);
    run_case("stop_different_lo",REMOTE_STOP,13,UINT64_C(802000000),UINT64_C(1102000000),0,1);
    run_case("negative_frequency_mismatch",REMOTE_ENABLE,14,UINT64_C(802000000),UINT64_C(1102000000),-5,1);
    run_case("negative_invalid_readback",REMOTE_STATUS,15,0,0,-4,0);
    return 0;
}
