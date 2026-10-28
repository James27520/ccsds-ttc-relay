/* Deterministic host mocks for service/real controller/core/serializer.
 * ADC and demod entrypoints are fakes, never RF or hardware evidence. */
#include "adda_service.h"
#include "waveform_fixture.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
const int16_t waveform_fixture[WAVEFORM_FIXTURE_COUNT]={0};
static struct {
    struct aps_state core;struct ac_capture cap;struct act_controller ctrl;
    struct atm_tx tx;struct asv_service service;struct ap_frame_result frame;
    uint32_t now,status,diag,flags,done_at,words[128],first[128];
    unsigned words_n,submits,stops,clears,udp,decodes,captures,cancels,stuck;
} e;
int adda_receive(const int16_t *p,size_t n,struct ap_frame_result *f,adda_demod_stats *stats)
{(void)p;(void)n;(void)stats;++e.decodes;*f=e.frame;return 1;}
int ac_probe(struct ac_capture *c){(void)c;return AC_OK;}
int ac_busy(const struct ac_capture *c){return c->state>=AC_CONFIG && c->state<=AC_RELEASING;}
int ac_start(struct ac_capture *c,uint32_t mode,unsigned ch,unsigned k,uint32_t now)
{(void)ch;(void)k;(void)now;++e.captures;c->desired_mode=mode;c->state=AC_READY;c->valid=1;return AC_OK;}
void ac_poll(struct ac_capture *c,uint32_t now){(void)c;(void)now;}
void ac_cancel(struct ac_capture *c,uint32_t now){(void)now;++e.cancels;c->state=AC_IDLE;c->valid=0;}
int ac_recover_cancel(struct ac_capture *c)
{assert(c->state==AC_ERROR && c->error==AC_ECANCEL);c->state=AC_IDLE;c->error=AC_OK;c->valid=0;return AC_OK;}
int ac_normal_ready(const struct ac_capture *c){return c->state==AC_READY && c->valid && c->desired_mode==TC_MODE_NORMAL;}
const char *ac_error_name(enum ac_error error){(void)error;return "mock";}
static uint32_t clock_ms(void *c){(void)c;return e.now;}
static int udp(void *c,uint32_t ip,uint16_t port,const uint8_t *p,size_t n)
{(void)c;(void)ip;(void)port;(void)p;assert(n==AP_RF_BYTES);++e.udp;return 0;}
static int rd(void *c,uint32_t address,uint32_t *v)
{
    (void)c;
    if(!e.stuck && e.status==19u && (int32_t)(e.now-e.done_at)>=0)e.status=8;
    switch(address-ATM_TX_BASE){case 0:*v=e.status;break;case 4:*v=e.diag;break;
    case 0x1c:*v=ATM_TX_MAGIC;break;case 0x20:*v=1;break;
    case 0x30:*v=0x102a0110;break;case 0x34:*v=e.flags;break;default:return -1;}return 0;
}
static int wr(void *c,uint32_t address,uint32_t v)
{
    (void)c;
    switch(address-ATM_TX_BASE){
    case 8:assert(!(e.status&197u) && !e.diag);++e.clears;e.words_n=0;e.status=2;break;
    case 12:assert(e.words_n<128);e.words[e.words_n++]=v;break;
    case 16:assert(v==3360u);break;
    case 20:assert(v==1 && e.words_n==105);++e.submits;e.status=19;e.done_at=e.now+34;
      if(e.submits==1)memcpy(e.first,e.words,sizeof(e.first));
      break;
    case 24:assert(v==1);++e.stops;
      if(e.status&1u){e.status=4;e.diag=64;}else e.status=2;break;
    default:return -1;}return 0;
}
static void barrier(void *c){(void)c;}
static void frame(unsigned seq)
{memset(&e.frame,0,sizeof(e.frame));e.frame.command.version=1;e.frame.command.seq=(uint8_t)seq;
 e.frame.command.rx_mhz=900;e.frame.command.tx_mhz=1001;
 assert(ap_body_build(&e.frame.command,e.frame.body)==AP_OK);}
static void setup(uint32_t now)
{
    struct aps_io io={0,0,udp};struct atm_io tm={0,rd,wr,barrier};struct act_clock clock={0,clock_ms};
    memset(&e,0,sizeof(e));e.now=now;e.status=2;e.flags=3;
    aps_init(&e.core,&io);e.core.network_ready=1;
    act_init(&e.ctrl,&e.core,&e.cap,&clock);assert(atm_tx_init(&e.tx,&tm)==AP_OK);
    assert(atm_tx_poll(&e.tx,1,e.now)==AP_OK);asv_init(&e.service,&e.ctrl,&e.tx);frame(1);
}
static void tick(uint32_t now)
{e.now=now;(void)atm_tx_poll(&e.tx,e.core.network_ready,now);asv_poll(&e.service,now);act_poll(&e.ctrl);}
static void accept(unsigned seq)
{
    frame(seq);act_poll(&e.ctrl);act_poll(&e.ctrl);
    assert(e.service.state==ASV_WAIT_ACK && !e.ctrl.automatic && e.core.transaction.pending);
}
static void ack(void)
{
    char text[128];int n;
    n=snprintf(text,sizeof(text),"rc=0 seq=%u rx_hz=900000000 tx_hz=1001000000\n",
               (unsigned)e.core.transaction.pending_transaction_seq);
    assert(aps_udp_received(&e.core,APS_RELAY_IPV4,APS_RELAY_PORT,(const uint8_t *)text,(size_t)n)==AP_OK);
    tick(e.now);assert(e.service.state==ASV_DELAY && !e.core.armed);
}
static void test_start_and_gate(void)
{
    char line[384];uint32_t started;
    setup(100);assert(!e.service.active && !e.ctrl.filter);
    e.core.network_ready=0;assert(asv_start(&e.service,e.now)<0);e.core.network_ready=1;
    e.core.rx_gain_db=1;assert(asv_start(&e.service,e.now)<0);e.core.rx_gain_db=0;
    e.flags=0;assert(asv_start(&e.service,e.now)<0);e.flags=3;
    assert(asv_start(&e.service,e.now)==AP_OK);started=e.service.started_ms;
    assert(asv_start(&e.service,e.now+500000)==AP_EBUSY && e.service.started_ms==started);
    assert(asv_status(&e.service,e.now,line,sizeof(line))>0 && strstr(line,"remaining_ms=600000"));
    assert(asv_status(&e.service,e.now,line,8)==AP_ELENGTH);
    assert(!asv_command_allowed(&e.service,"decode") && !asv_command_allowed(&e.service,"tmsend"));
    assert(!asv_command_allowed(&e.service,"nettest 900 1001 2 0 89"));
    assert(!asv_command_allowed(&e.service,"levels 0 89") && !asv_command_allowed(&e.service,"auto on"));
    assert(asv_command_allowed(&e.service,"telemetry") && asv_cancel_command("capture cancel"));
    assert(asv_cancel_command("tmstop") && asv_cancel_command("network off"));
}
static void test_immutable_400_replies(void)
{
    unsigned i,decodes;uint32_t at;uint8_t frozen[ATM_BURST_BYTES];
    setup(100);assert(asv_start(&e.service,e.now)==0);accept(4);decodes=e.decodes;
    tick(120);assert(e.core.armed && e.decodes==decodes);ack();at=e.service.ack_ms;
    memcpy(frozen,e.service.burst,sizeof(frozen));
    tick(at+2999);assert(!e.submits);
    for(i=0;i<400;++i){tick(at+3000+i*50);assert(e.submits==i+1);
      assert(!memcmp(e.first,e.words,sizeof(e.first)) && !memcmp(frozen,e.service.burst,sizeof(frozen)));
      assert(e.tx.sequence==1 && e.decodes==decodes && e.udp==1);}
    tick(at+23000);assert(e.service.completed==1 && e.service.state==ASV_LISTEN && e.core.armed);
    /* Repeats, including A -> B -> A, never update decoded or resend UDP. */
    frame(4);act_poll(&e.ctrl);assert(e.udp==1 && e.core.decoded_frames==1);
    accept(5);ack();tick(e.service.ack_ms+23000);assert(e.service.failed==1); /* No catch-up sends. */
    frame(4);act_poll(&e.ctrl);act_poll(&e.ctrl);assert(e.udp==2 && e.core.decoded_frames==2);
    e.frame.command.rx_mhz=901;assert(ap_body_build(&e.frame.command,e.frame.body)==0);
    act_poll(&e.ctrl);act_poll(&e.ctrl);assert(e.udp==2 && e.service.used_count==2);
}
static void test_udp_timeout_no_success_reply(void)
{
    setup(0);assert(asv_start(&e.service,e.now)==0);accept(7);
    tick(250);tick(500);assert(e.udp==3 && e.service.state==ASV_WAIT_ACK);
    tick(750);tick(751);assert(!e.core.transaction.pending && !e.submits && e.service.failed==1);
    assert(e.service.state==ASV_LISTEN);frame(7);act_poll(&e.ctrl);act_poll(&e.ctrl);assert(e.udp==3);
}
static void test_cancel_fault_disconnect_lease(void)
{
    unsigned clears;uint32_t at;
    setup(0);assert(asv_start(&e.service,0)==0);accept(8);ack();at=e.service.ack_ms;
    tick(at+3000);clears=e.clears;e.diag=1;e.status=12;
    tick(at+3050);assert(!e.service.active && e.service.reason==ASV_TM && e.clears==clears);
    tick(at+3100);assert(e.submits==1); /* Never clear/retry a fault. */
    setup(0);assert(asv_start(&e.service,0)==0);accept(9);ack();e.core.network_ready=0;
    tick(3000);assert(!e.service.active && !e.submits && e.service.reason==ASV_NETWORK);
    e.core.network_ready=1;tick(4000);assert(!e.service.active && !e.submits);
    setup(0);assert(asv_start(&e.service,0)==0);accept(9);
    assert(asv_stop(&e.service,ASV_USER,10)==0 && !e.core.armed && !e.core.transaction.pending);
    tick(4000);assert(!e.submits && !e.ctrl.filter);
    setup(UINT32_MAX-100);assert(asv_start(&e.service,e.now)==0);
    tick((uint32_t)(e.service.started_ms+ASV_LEASE_MS));
    assert(!e.service.active && !e.core.armed && e.service.reason==ASV_LEASE);
    setup(0);assert(asv_start(&e.service,0)==0);accept(2);ack();tick(3000);e.stuck=1;
    tick(3100);assert(!e.service.active && e.service.reason==ASV_TM && e.submits==1);
}
static void test_absolute_window_and_limit(void)
{
    unsigned i;uint32_t at;
    setup(0);assert(asv_start(&e.service,0)==0);accept(10);ack();at=e.service.ack_ms;
    tick(at+3000);tick(at+3100);assert(e.submits==2);
    tick(at+22980);assert(e.submits==2);tick(at+23000);
    assert(e.service.state==ASV_LISTEN && e.service.completed==1); /* No late burst. */
    setup(0);assert(asv_start(&e.service,0)==0);
    for(i=0;i<16;++i){accept(i);ack();at=e.service.ack_ms;
      tick(at+3000);tick(at+23000);}
    assert(e.service.accepted==16 && !e.service.active && e.service.reason==ASV_LIMIT);
    assert(e.submits==16 && e.tx.sequence==16 && !e.core.armed);
}
static void test_explicit_cancel_restart_and_real_fault_rejection(void)
{
    setup(0);e.cap.state=AC_ERROR;e.cap.error=AC_ECANCEL;
    assert(asv_start(&e.service,0)==0 && e.cap.state==AC_IDLE && !e.cap.valid);
    assert(asv_stop(&e.service,ASV_USER,1)==0);tick(2);
    assert(e.service.state==ASV_OFF && !e.core.armed);
    assert(asv_start(&e.service,3)==0); /* Explicit on starts a fresh lease. */
    setup(0);e.cap.state=AC_ERROR;e.cap.error=AC_ECONFIG;
    assert(asv_start(&e.service,0)==AP_EBUSY && e.cap.error==AC_ECONFIG);
    setup(0);assert(asv_start(&e.service,0)==0);accept(12);ack();
    assert(!e.core.armed && !e.core.transaction.pending && e.core.applied_commands==1);
    /* Disarming after the ACK preserves every applied/ACK record. */
    assert(e.core.last_ack.record.valid && e.core.last_ack.record.command.seq==12);
}
static void test_retired_reply_is_never_used_for_failed_next_transaction(void)
{
    uint32_t at;unsigned submits;
    setup(0);assert(asv_start(&e.service,0)==0);accept(40);ack();at=e.service.ack_ms;
    tick(at+3000);tick(at+23000);submits=e.submits;assert(submits==1);
    accept(41);at=e.now;
    tick(at+250);tick(at+500);tick(at+750);tick(at+751);
    assert(e.service.failed==1 && e.submits==submits && e.core.applied_commands==1);
    assert(e.core.last_ack.record.command.seq==40 && e.service.state==ASV_LISTEN);
    tick(at+4000);assert(e.submits==submits);
    /* Simulate platform cancellation dispatch before legacy arm-off semantics. */
    accept(42);assert(asv_cancel_command("arm off"));
    assert(asv_stop(&e.service,ASV_USER,e.now)==0);
    assert(act_command_line(&e.ctrl,"arm off")==0);
    tick(e.now+4000);assert(!e.core.transaction.pending && !e.core.armed && e.submits==submits);
}
int main(void)
{
    test_start_and_gate();test_immutable_400_replies();test_udp_timeout_no_success_reply();
    test_cancel_fault_disconnect_lease();test_absolute_window_and_limit();
    test_explicit_cancel_restart_and_real_fault_rejection();
    test_retired_reply_is_never_used_for_failed_next_transaction();
    setup(0);assert(!e.ctrl.filter);frame(99);e.cap.state=AC_READY;e.cap.valid=1;e.cap.desired_mode=TC_MODE_NORMAL;
    assert(act_command_line(&e.ctrl,"decode")==0 && e.core.decoded_frames==1 && !e.udp);
    puts("PASS autonomous service: mock ADC/controller/UDP ACK, immutable bounded replies, replay/stop/fault/lease; no hardware");
    return 0;
}
