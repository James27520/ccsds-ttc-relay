#ifndef RELAY_REMOTE_PACKET_H
#define RELAY_REMOTE_PACKET_H
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define REMOTE_COMMAND_SIZE 34u
#define REMOTE_ACK_SIZE 50u
#define REMOTE_ENABLE 0x21u
#define REMOTE_STOP 0x22u
#define REMOTE_STATUS 0x23u
#define REMOTE_VALID 1u
#define REMOTE_ACTIVE 2u
#define REMOTE_EXPIRED 4u
#define REMOTE_FAULT 8u

struct remote_command {
    uint16_t seq;
    uint8_t op, mode, gain, attenuation;
    uint32_t lease_ms;
    uint64_t rx_hz, tx_hz;
};
struct remote_snapshot {
    uint8_t flags, mode, gain[2];
    uint32_t attenuation[2], remaining_ms, uptime_ms;
    uint64_t rx_hz, tx_hz;
    int32_t rc;
};
static uint16_t remote_u16(const uint8_t *p) {
    return (uint16_t)(((uint16_t)p[0]<<8)|p[1]);
}
static uint32_t remote_u32(const uint8_t *p) {
    return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];
}
static uint64_t remote_u64(const uint8_t *p) {
    return ((uint64_t)remote_u32(p)<<32)|remote_u32(p+4);
}
static void remote_put16(uint8_t *p, uint16_t v) { p[0]=(uint8_t)(v>>8); p[1]=(uint8_t)v; }
static void remote_put32(uint8_t *p, uint32_t v) {
    p[0]=(uint8_t)(v>>24); p[1]=(uint8_t)(v>>16); p[2]=(uint8_t)(v>>8); p[3]=(uint8_t)v;
}
static void remote_put64(uint8_t *p, uint64_t v) {
    remote_put32(p,(uint32_t)(v>>32)); remote_put32(p+4,(uint32_t)v);
}
static uint16_t remote_crc(const uint8_t *p, size_t n) {
    uint16_t crc=0xffffu;
    size_t i; unsigned b;
    for(i=0;i<n;++i) {
        crc^=(uint16_t)p[i]<<8;
        for(b=0;b<8;++b) crc=(uint16_t)((crc<<1)^((crc&0x8000u)?0x1021u:0u));
    }
    return crc;
}
/* Parse into a temporary value: no malformed input can partly update state. */
static int remote_parse(const uint8_t *p, size_t n, struct remote_command *out) {
    struct remote_command c;
    if(!p || !out || n!=REMOTE_COMMAND_SIZE || remote_u16(p)!=0x0120u ||
       (remote_u16(p+2)&0xc000u)!=0xc000u || remote_u16(p+4)!=27u ||
       p[6]!=1u || p[11] || remote_crc(p,n-2)!=remote_u16(p+n-2)) return -1;
    c.seq=remote_u16(p+2)&0x3fffu; c.op=p[7]; c.mode=p[8];
    c.gain=p[9]; c.attenuation=p[10]; c.lease_ms=remote_u32(p+12);
    c.rx_hz=remote_u64(p+16); c.tx_hz=remote_u64(p+24);
    if(c.rx_hz<70000000ULL || c.rx_hz>6000000000ULL ||
       c.tx_hz<70000000ULL || c.tx_hz>6000000000ULL) return -1;
    if(c.op==REMOTE_ENABLE) {
        if(c.mode!=1u || c.gain>30u || c.attenuation<50u || c.attenuation>89u ||
           c.lease_ms<2000u || c.lease_ms>300000u) return -1;
    } else if(c.op==REMOTE_STOP || c.op==REMOTE_STATUS) {
        if(c.mode || c.gain || c.attenuation || c.lease_ms) return -1;
    } else return -1;
    *out=c; return 0;
}
static void remote_encode_ack(uint8_t out[REMOTE_ACK_SIZE], uint16_t seq,
                              uint8_t op, const struct remote_snapshot *s) {
    memset(out,0,REMOTE_ACK_SIZE);
    remote_put16(out,0x0220u); remote_put16(out+2,(uint16_t)(0xc000u|(seq&0x3fffu)));
    remote_put16(out+4,43u); out[6]=1; out[7]=op; out[8]=s->flags;
    out[9]=s->mode; out[10]=s->gain[0]; out[11]=s->gain[1];
    remote_put32(out+12,s->attenuation[0]); remote_put32(out+16,s->attenuation[1]);
    remote_put32(out+20,s->remaining_ms); remote_put32(out+24,s->uptime_ms);
    remote_put64(out+28,s->rx_hz); remote_put64(out+36,s->tx_hz);
    remote_put32(out+44,(uint32_t)s->rc); remote_put16(out+48,remote_crc(out,48));
}
#endif
