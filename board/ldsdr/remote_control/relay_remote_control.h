#ifndef RELAY_REMOTE_CONTROL_H
#define RELAY_REMOTE_CONTROL_H
#include "relay_remote_packet.h"

/* All callbacks execute in the bounded main-loop path, never an ISR. */
struct remote_hardware {
    void *context;
    uint64_t (*now_ms)(void *);
    int (*mode)(void *, unsigned);
    int (*gain)(void *, unsigned, unsigned);
    int (*attenuation)(void *, unsigned, uint32_t);
    int (*read)(void *, struct remote_snapshot *);
    int (*radio_ok)(void *);
};
struct remote_state {
    struct remote_hardware hw;
    uint64_t deadline_ms;
    uint8_t active, expired, fault, seen, last_started;
    uint8_t target_gain, target_attenuation;
    uint64_t target_rx_hz, target_tx_hz;
    uint16_t last_seq;
    int last_rc;
    uint8_t last_packet[REMOTE_COMMAND_SIZE];
};
static int remote_close(uint64_t a,uint64_t b) { return a>b ? a-b<=10000u : b-a<=10000u; }
static int remote_read(struct remote_state *s,struct remote_snapshot *v) {
    memset(v,0,sizeof(*v));
    if(s->hw.read(s->hw.context,v)) { memset(v,0,sizeof(*v)); return -4; }
    v->flags=REMOTE_VALID; return 0;
}
/* PL mute ALWAYS precedes any SPI operation. Attempt every safety write even
 * after a failure; there is no RF rollback to an enabled state. */
static int remote_safe(struct remote_state *s) {
    struct remote_snapshot v;
    int bad=0; unsigned ch;
    s->active=0; s->deadline_ms=0;
    if(s->hw.mode(s->hw.context,2)) bad=1;
    for(ch=0;ch<2;++ch) if(s->hw.attenuation(s->hw.context,ch,89000)) bad=1;
    for(ch=0;ch<2;++ch) if(s->hw.gain(s->hw.context,ch,0)) bad=1;
    if(remote_read(s,&v) || v.mode!=2 || v.attenuation[0]!=89000 ||
       v.attenuation[1]!=89000 || v.gain[0] || v.gain[1]) bad=1;
    if(bad) s->fault=1;
    return bad ? -4 : 0;
}
static void remote_init(struct remote_state *s,const struct remote_hardware *hw) {
    memset(s,0,sizeof(*s)); s->hw=*hw;
}
static void remote_tick(struct remote_state *s) {
    if(s->active && s->hw.now_ms(s->hw.context)>=s->deadline_ms) {
        s->expired=1; (void)remote_safe(s);
    }
}
/* Verify the entire lease envelope when taking a snapshot, including mode.
 * Failed reads latch a fault and mute before returning an invalid snapshot. */
static int remote_snapshot(struct remote_state *s,struct remote_snapshot *v) {
    int rc;
    remote_tick(s); rc=remote_read(s,v);
    if(rc) { (void)remote_safe(s); s->fault=1; memset(v,0,sizeof(*v)); }
    remote_tick(s);
    if(!rc && s->active && (v->mode!=1 || v->gain[0]!=s->target_gain ||
       v->gain[1]!=s->target_gain || v->attenuation[0]!=(uint32_t)s->target_attenuation*1000u ||
       v->attenuation[1]!=(uint32_t)s->target_attenuation*1000u ||
       !remote_close(v->rx_hz,s->target_rx_hz) || !remote_close(v->tx_hz,s->target_tx_hz))) {
        (void)remote_safe(s); s->fault=1; memset(v,0,sizeof(*v)); rc=-4;
    }
    /* If reading crossed the deadline, return a fresh post-mute snapshot. */
    if(!rc && !s->active && v->mode!=2) {
        (void)remote_safe(s);
        rc=remote_read(s,v);
        if(rc) { s->fault=1; memset(v,0,sizeof(*v)); }
    }
    v->uptime_ms=(uint32_t)s->hw.now_ms(s->hw.context);
    if(s->active) {
        uint64_t now=s->hw.now_ms(s->hw.context);
        if(now<s->deadline_ms) { v->flags|=REMOTE_ACTIVE; v->remaining_ms=(uint32_t)(s->deadline_ms-now); }
    }
    if(s->expired) v->flags|=REMOTE_EXPIRED;
    if(s->fault) v->flags|=REMOTE_FAULT;
    return rc;
}
static int remote_enable(struct remote_state *s,const struct remote_command *c) {
    struct remote_snapshot v;
    unsigned ch; int bad=0;
    if(s->fault) return -7;
    if(remote_safe(s)) return -4;
    if(remote_read(s,&v) || s->hw.radio_ok(s->hw.context)) {
        (void)remote_safe(s); s->fault=1; return -4;
    }
    if(!remote_close(v.rx_hz,c->rx_hz) || !remote_close(v.tx_hz,c->tx_hz)) return -5;
    for(ch=0;ch<2;++ch) if(s->hw.gain(s->hw.context,ch,c->gain)) bad=1;
    for(ch=0;ch<2;++ch) if(s->hw.attenuation(s->hw.context,ch,(uint32_t)c->attenuation*1000u)) bad=1;
    if(remote_read(s,&v) || v.mode!=2 ||
       !remote_close(v.rx_hz,c->rx_hz) || !remote_close(v.tx_hz,c->tx_hz) ||
       v.gain[0]!=c->gain || v.gain[1]!=c->gain ||
       v.attenuation[0]!=(uint32_t)c->attenuation*1000u ||
       v.attenuation[1]!=(uint32_t)c->attenuation*1000u || s->hw.radio_ok(s->hw.context)) bad=1;
    if(bad) { (void)remote_safe(s); s->fault=1; return -4; }
    /* Deadline starts before enabling the PL and never follows duplicate ACKs. */
    s->deadline_ms=s->hw.now_ms(s->hw.context)+c->lease_ms;
    s->target_gain=c->gain; s->target_attenuation=c->attenuation;
    s->target_rx_hz=c->rx_hz; s->target_tx_hz=c->tx_hz;
    s->active=1;
    if(s->hw.mode(s->hw.context,1) || remote_read(s,&v) || v.mode!=1) {
        (void)remote_safe(s); s->fault=1; return -4;
    }
    s->last_started=1;
    remote_tick(s);
    return s->active ? 0 : -6;
}
/* Invalid packets never enter sequence state, including invalid CRCs/ranges. */
static int remote_process(struct remote_state *s,const uint8_t *packet,size_t n,
                          uint8_t ack[REMOTE_ACK_SIZE]) {
    struct remote_command c;
    struct remote_snapshot v;
    uint16_t seq=(packet && n>=4)?remote_u16(packet+2)&0x3fffu:0;
    uint8_t op=(packet && n>=8)?packet[7]:0;
    int rc=remote_parse(packet,n,&c);
    remote_tick(s);
    if(!rc) {
        seq=c.seq; op=c.op;
        if(s->seen && c.seq<s->last_seq) rc=-2;
        else if(s->seen && c.seq==s->last_seq) {
            if(memcmp(packet,s->last_packet,REMOTE_COMMAND_SIZE)) rc=-3;
            else if(c.op==REMOTE_ENABLE && s->last_started && !s->active) rc=-6;
            else rc=s->last_rc;
        } else {
            s->seen=1; s->last_seq=c.seq; s->last_started=0;
            memcpy(s->last_packet,packet,REMOTE_COMMAND_SIZE);
            if(c.op==REMOTE_STOP) rc=remote_safe(s);
            else if(c.op==REMOTE_ENABLE) rc=remote_enable(s,&c);
            s->last_rc=rc;
        }
    }
    if(remote_snapshot(s,&v)) {
        rc=-4;
        if(s->seen && seq==s->last_seq && n==REMOTE_COMMAND_SIZE &&
           !memcmp(packet,s->last_packet,REMOTE_COMMAND_SIZE)) s->last_rc=rc;
    }
    if(!rc && c.op==REMOTE_ENABLE && !s->active) rc=-6;
    v.rc=rc; remote_encode_ack(ack,seq,op,&v); return rc;
}
#endif
