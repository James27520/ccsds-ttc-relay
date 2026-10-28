#include <assert.h>
#include <stdio.h>
#include "relay_remote_control.h"

struct mock {
    uint64_t now;
    struct remote_snapshot actual;
    unsigned writes,reads,modes,enable_modes;
    int fail_write,fail_read,fail_radio,mismatch,read_advance;
    unsigned trace[128],trace_n;
};
static struct mock m;
static struct remote_state state;
static uint8_t packet[REMOTE_COMMAND_SIZE],ack[REMOTE_ACK_SIZE];
static uint64_t now_ms(void *p) { return ((struct mock *)p)->now; }
static int write_op(struct mock *x,unsigned tag) {
    ++x->writes;
    if(x->trace_n<128) x->trace[x->trace_n++]=tag;
    return x->fail_write && (int)x->writes==x->fail_write;
}
static int set_mode(void *p,unsigned v) {
    struct mock *x=p; int fail=write_op(x,100+v);
    ++x->modes; if(v==1) ++x->enable_modes;
    if(!fail) x->actual.mode=(uint8_t)v;
    return fail;
}
static int set_gain(void *p,unsigned ch,unsigned v) {
    struct mock *x=p; int fail=write_op(x,200+ch);
    if(!fail) x->actual.gain[ch]=(uint8_t)v;
    return fail;
}
static int set_att(void *p,unsigned ch,uint32_t v) {
    struct mock *x=p; int fail=write_op(x,300+ch);
    if(!fail) x->actual.attenuation[ch]=v;
    return fail;
}
static int read_hw(void *p,struct remote_snapshot *v) {
    struct mock *x=p; ++x->reads; x->now+=(unsigned)x->read_advance;
    *v=x->actual;
    if(x->mismatch) v->gain[1]^=1;
    return x->fail_read;
}
static int radio_ok(void *p) { return ((struct mock *)p)->fail_radio; }
static void reset(void) {
    struct remote_hardware hw={&m,now_ms,set_mode,set_gain,set_att,read_hw,radio_ok};
    memset(&m,0,sizeof(m)); m.actual.mode=2;
    m.actual.attenuation[0]=m.actual.attenuation[1]=89000;
    m.actual.rx_hz=900000000; m.actual.tx_hz=1000000000;
    remote_init(&state,&hw);
}
static void crc(void) { remote_put16(packet+32,remote_crc(packet,32)); }
static void command(unsigned seq,unsigned op,unsigned lease) {
    memset(packet,0,sizeof(packet)); remote_put16(packet,0x0120);
    remote_put16(packet+2,(uint16_t)(0xc000|seq)); remote_put16(packet+4,27);
    packet[6]=1; packet[7]=(uint8_t)op;
    if(op==REMOTE_ENABLE) { packet[8]=1;packet[9]=30;packet[10]=50;remote_put32(packet+12,lease); }
    remote_put64(packet+16,900000000); remote_put64(packet+24,1000000000); crc();
}
static int run(void) {
    int rc=remote_process(&state,packet,sizeof(packet),ack);
    assert(remote_u16(ack)==0x0220 && remote_u16(ack+4)==43 && ack[6]==1);
    assert(remote_crc(ack,48)==remote_u16(ack+48));
    assert((int32_t)remote_u32(ack+44)==rc); return rc;
}
static void safe(void) {
    assert(!state.active && m.actual.mode==2 && m.actual.gain[0]==0 && m.actual.gain[1]==0);
    assert(m.actual.attenuation[0]==89000 && m.actual.attenuation[1]==89000);
}
int main(void) {
    unsigned i,writes; uint64_t deadline;
    struct remote_command c;
    reset(); assert(remote_crc((const uint8_t *)"123456789",9)==0x29b1);
    command(0x123,REMOTE_ENABLE,300000); assert(!remote_parse(packet,sizeof(packet),&c));
    assert(c.seq==0x123 && c.lease_ms==300000 && c.rx_hz==900000000 && c.tx_hz==1000000000);
    for(i=0;i<sizeof(packet);++i) {
        packet[i]^=1; assert(remote_parse(packet,sizeof(packet),&c)==-1); packet[i]^=1;
    }
    assert(remote_parse(packet,33,&c)==-1 && remote_parse(packet,35,&c)==-1);
    assert(remote_parse(NULL,34,&c)==-1 && remote_parse(packet,34,NULL)==-1);
    puts("PASS: exact codec framing, endian, CRC golden and every-byte corruption");

    reset(); command(1,REMOTE_ENABLE,2000); assert(run()==0);
    assert(state.active && m.actual.mode==1 && ack[8]==(REMOTE_VALID|REMOTE_ACTIVE));
    assert(ack[10]==30 && ack[11]==30 && remote_u32(ack+12)==50000 && remote_u32(ack+16)==50000);
    assert(remote_u32(ack+20)==2000 && remote_u64(ack+28)==900000000);
    assert(m.trace[0]==102 && m.trace[1]==300 && m.trace[2]==301);
    deadline=state.deadline_ms; writes=m.writes; m.now=1999;
    assert(run()==0 && state.deadline_ms==deadline && m.writes==writes && remote_u32(ack+20)==1);
    m.now=2000; assert(run()==-6); safe(); assert(state.expired);
    writes=m.writes; assert(run()==-6 && m.writes==writes);
    puts("PASS: active actual dual-channel ACK, duplicate never writes/renews, exact expiry boundary");

    reset(); command(1,REMOTE_ENABLE,300000); assert(run()==0);deadline=state.deadline_ms;
    m.now=900; command(2,REMOTE_STATUS,0);writes=m.writes;
    assert(run()==0 && state.deadline_ms==deadline && m.writes==writes);
    command(3,REMOTE_STOP,0); assert(run()==0);safe();
    assert(ack[8]==REMOTE_VALID && ack[9]==2 && !ack[10] && !ack[11] && !remote_u32(ack+20));
    puts("PASS: status is read-only and stop confirms both 89dB/0dB without LO changes");

    reset();command(8,REMOTE_ENABLE,2000);assert(run()==0);writes=m.writes;
    packet[9]=29;crc();assert(run()==-3 && m.writes==writes);
    command(7,REMOTE_STOP,0);assert(run()==-2 && state.active && m.writes==writes);
    command(9,REMOTE_STATUS,0);assert(run()==0);
    command(8,REMOTE_ENABLE,2000);assert(run()==-2);
    puts("PASS: same-sequence conflict, old sequence rejection and status consumes sequence");

    reset();command(16383,REMOTE_STATUS,0);assert(run()==0);
    command(0,REMOTE_ENABLE,2000);assert(run()==-2 && !state.active);
    reset();command(10,REMOTE_ENABLE,2000);packet[32]^=1;assert(run()==-1 && !state.seen);
    command(1,REMOTE_STATUS,0);assert(run()==0 && state.last_seq==1);
    puts("PASS: no sequence wrap and invalid CRC does not consume sequence");

    reset();command(2,REMOTE_ENABLE,2000);remote_put64(packet+16,901000000);crc();
    assert(run()==-5);safe();writes=m.writes;assert(run()==-5 && m.writes==writes);
    command(1,REMOTE_STATUS,0);assert(run()==-2);
    command(3,REMOTE_ENABLE,2000);assert(run()==0);assert(!remote_safe(&state));
    assert(run()==-6);safe();
    puts("PASS: frequency mismatch consumes seq, cached failure and cancelled enable cannot restart");

    for(i=1;i<=10;++i) {
        reset();m.fail_write=(int)i;command(1,REMOTE_ENABLE,2000);
        assert(run()==-4 && state.fault && !state.active);
        assert(m.actual.mode==2);command(2,REMOTE_ENABLE,2000);
        assert(run()==-7 && !state.active);
    }
    puts("PASS: every enable write failure attempts mute and permanently refuses enable");

    reset();m.fail_read=1;command(1,REMOTE_STATUS,0);assert(run()==-4 && state.fault);
    assert(!(ack[8]&REMOTE_VALID) && (ack[8]&REMOTE_FAULT));
    assert(!ack[9] && !ack[10] && !remote_u32(ack+12) && !remote_u64(ack+28));
    m.fail_read=0;command(2,REMOTE_ENABLE,2000);assert(run()==-7);safe();
    reset();m.mismatch=1;command(1,REMOTE_ENABLE,2000);assert(run()==-4 && state.fault && !state.active);
    reset();m.fail_radio=1;command(1,REMOTE_ENABLE,2000);assert(run()==-4);safe();
    puts("PASS: read failure clears validity/unknown values, dual-channel mismatch and radio failure latch");

    reset();command(1,REMOTE_ENABLE,2000);assert(run()==0);
    m.now=2000;m.fail_write=(int)m.writes+2;remote_tick(&state);
    assert(state.expired && state.fault && !state.active && m.actual.mode==2);
    command(2,REMOTE_ENABLE,2000);assert(run()==-7);
    reset();command(1,REMOTE_ENABLE,2000);assert(run()==0);
    m.now=1999;m.read_advance=2;command(2,REMOTE_STATUS,0);assert(run()==0);safe();
    assert(!(ack[8]&REMOTE_ACTIVE) && (ack[8]&REMOTE_EXPIRED) && ack[9]==2);
    puts("PASS: expiry write failure latches and snapshot crossing deadline reports fresh stopped state");

    reset();m.now=0xffffff00ULL;command(1,REMOTE_ENABLE,2000);assert(run()==0);
    m.now+=1500;command(2,REMOTE_STATUS,0);assert(run()==0);
    assert(remote_u32(ack+24)==(uint32_t)m.now && remote_u32(ack+20)==500);
    m.now+=500;remote_tick(&state);safe();
    puts("PASS: uptime low32 wrap does not shorten or extend 64-bit lease");

    reset();command(1,REMOTE_ENABLE,2000);assert(run()==0);
    m.actual.attenuation[1]=49999;command(2,REMOTE_STATUS,0);assert(run()==-4 && state.fault);safe();
    puts("PASS: unexpected active hardware state fails closed instead of echoing requests");

    for(i=0;i<8;++i) {
        reset();command(1,REMOTE_ENABLE,2000);
        switch(i) {
        case 0:packet[8]=0;break;case 1:packet[9]=31;break;case 2:packet[10]=49;break;
        case 3:packet[10]=90;break;case 4:remote_put32(packet+12,1999);break;
        case 5:remote_put32(packet+12,300001);break;case 6:packet[11]=1;break;
        default:remote_put64(packet+24,6000000001ULL);break;
        }
        crc();assert(run()==-1 && !state.seen && !m.writes);
    }
    reset();command(1,REMOTE_STOP,0);packet[9]=1;crc();assert(run()==-1 && !state.seen);
    puts("PASS: fixed field/range validation never executes or consumes malformed commands");
    return 0;
}
