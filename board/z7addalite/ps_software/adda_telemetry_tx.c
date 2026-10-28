#include "adda_telemetry_tx.h"
#include <string.h>
static void put16(uint8_t *p,uint16_t v){p[0]=(uint8_t)(v>>8);p[1]=(uint8_t)v;}
static void put32(uint8_t *p,uint32_t v){put16(p,(uint16_t)(v>>16));put16(p+2,(uint16_t)v);}
static void put64(uint8_t *p,uint64_t v){put32(p,(uint32_t)(v>>32));put32(p+4,(uint32_t)v);}
static int record_valid(const struct aps_command_record *r)
{
    return r->valid<=1u && (!r->valid ||
      (r->origin>=APS_ADC_NORMAL && r->origin<=APS_UART_NETTEST &&
       r->command.rx_mhz>=70u && r->command.rx_mhz<=6000u &&
       r->command.tx_mhz>=70u && r->command.tx_mhz<=6000u));
}
static void put_record(uint8_t *p,const struct aps_command_record *r)
{
    if(!r->valid)return;
    put32(p,r->event);p[4]=(uint8_t)r->origin;p[5]=r->command.seq;
    put16(p+6,r->command.rx_mhz);put16(p+8,r->command.tx_mhz);
}
int atm_pack(const struct aps_state *s,uint32_t sequence,uint32_t uptime,
             uint8_t *out,size_t capacity)
{
    uint8_t p[ATM_PAYLOAD_BYTES];
    if(!s || !out)return AP_EARG;
    if(capacity<sizeof(p))return AP_ELENGTH;
    if(!record_valid(&s->last_decoded) || !record_valid(&s->last_send.record) ||
       !record_valid(&s->last_ack.record) || s->last_send.count>255u ||
       (s->last_ack.record.valid && s->last_ack.reply.rc!=0))return AP_EARG;
    memset(p,0,sizeof(p));memcpy(p,"ATM1",4);p[4]=1;
    p[5]=(uint8_t)((!!s->network_ready) | ((!!s->armed)<<1) |
      ((!!s->transaction.pending)<<2) | ((!!s->last_decoded.valid)<<3) |
      ((!!s->last_send.record.valid)<<4) | ((!!s->last_ack.record.valid)<<5));
    put32(p+8,sequence);put32(p+12,uptime);put32(p+16,s->telemetry_events);
    put32(p+20,s->decoded_frames);put32(p+24,s->applied_commands);put32(p+28,s->failed_transactions);
    put_record(p+32,&s->last_decoded);put_record(p+42,&s->last_send.record);
    if(s->last_send.record.valid){put16(p+52,s->last_send.transaction_seq);p[54]=(uint8_t)s->last_send.count;put32(p+56,(uint32_t)s->last_send.rc);}
    put_record(p+60,&s->last_ack.record);
    if(s->last_ack.record.valid){put16(p+70,s->last_ack.reply.seq);put32(p+72,(uint32_t)s->last_ack.reply.rc);put64(p+76,s->last_ack.reply.rx_hz);put64(p+84,s->last_ack.reply.tx_hz);}
    memcpy(out,p,sizeof(p));return (int)sizeof(p);
}
int atm_frame(const uint8_t *payload,size_t length,uint8_t *out,size_t capacity)
{
    uint16_t crc;
    if(!payload || !out)return AP_EARG;
    if(length!=ATM_PAYLOAD_BYTES || capacity<ATM_FRAME_BYTES)return AP_ELENGTH;
    crc=ap_crc16(payload,length);out[0]=out[1]=0xaa;out[2]=(uint8_t)length;
    memcpy(out+3,payload,length);put16(out+3+length,crc);return ATM_FRAME_BYTES;
}
int atm_burst(const struct aps_state *s,uint32_t sequence,uint32_t uptime,uint8_t *out,size_t capacity)
{
    uint8_t p[ATM_PAYLOAD_BYTES],frame[ATM_FRAME_BYTES];unsigned i;int rc;
    if(!out)return AP_EARG;
    if(capacity<ATM_BURST_BYTES)return AP_ELENGTH;
    rc=atm_pack(s,sequence,uptime,p,sizeof(p));if(rc<0)return rc;
    rc=atm_frame(p,sizeof(p),frame,sizeof(frame));if(rc<0)return rc;
    memset(out,0xaa,8);for(i=0;i<ATM_REPEAT_COUNT;++i)memcpy(out+8+i*ATM_FRAME_BYTES,frame,sizeof(frame));
    memset(out+8+ATM_REPEAT_COUNT*ATM_FRAME_BYTES,0xaa,8);return ATM_BURST_BYTES;
}
uint32_t atm_word(const uint8_t *bytes,size_t length,size_t index)
{
    unsigned i;uint32_t word=0;size_t at;
    if(!bytes || index>=ATM_BUFFER_BYTES/4u)return 0;
    at=index*4u;for(i=0;i<4u;++i)word=(word<<8) | (at+i<length?bytes[at+i]:0u);
    return word;
}
#if ADDA_TM_TX_ENABLED
static int rd(struct atm_tx *t,uint32_t reg,uint32_t *v)
{return t->io.read32(t->io.context,ATM_TX_BASE+reg,v)==0?AP_OK:AP_EREMOTE;}
static int wr(struct atm_tx *t,uint32_t reg,uint32_t v)
{return t->io.write32(t->io.context,ATM_TX_BASE+reg,v)==0?AP_OK:AP_EREMOTE;}
#endif
int atm_tx_status(struct atm_tx *t,uint32_t *status,uint32_t *diag)
{
#if ADDA_TM_TX_ENABLED
    uint32_t magic,abi;
    if(!t || !status || !diag || !t->io.read32 || !t->io.write32 || !t->io.barrier)return AP_EARG;
    if(rd(t,0x1c,&magic)<0 || rd(t,0x20,&abi)<0)return AP_EREMOTE;
    if(magic!=ATM_TX_MAGIC || abi!=1u)return AP_EMISMATCH;
    if(rd(t,0,status)<0 || rd(t,4,diag)<0)return AP_EREMOTE;
    return AP_OK;
#else
    (void)t;(void)status;(void)diag;return ATM_TX_DISABLED;
#endif
}
int atm_tx_configuration(struct atm_tx *t,uint32_t *flags,uint32_t *diagnostic)
{
#if ADDA_TM_TX_ENABLED
    uint32_t status,diag;int rc;
    if(!flags || !diagnostic)return AP_EARG;
    rc=atm_tx_status(t,&status,&diag);if(rc<0)return rc;
    if(rd(t,0x30,diagnostic)<0 || rd(t,0x34,flags)<0)return AP_EREMOTE;
    return AP_OK;
#else
    (void)t;(void)flags;(void)diagnostic;return ATM_TX_DISABLED;
#endif
}
int atm_tx_stop(struct atm_tx *t)
{
#if ADDA_TM_TX_ENABLED
    uint32_t status,diag;int rc=atm_tx_status(t,&status,&diag);
    if(rc<0)return rc;
    /* Peripheral reset rejects writes with AXI SLVERR. The standalone CPU's
     * MMIO adapter cannot turn a data abort into a normal callback error. */
    if(status&128u){t->stopping=2u;return AP_PENDING;}
    rc=wr(t,0x18,1u);if(rc<0)return rc;
    t->io.barrier(t->io.context);t->stopping=1u;return AP_OK;
#else
    (void)t;return ATM_TX_DISABLED;
#endif
}
int atm_tx_init(struct atm_tx *t,const struct atm_io *io)
{
    if(!t || !io)return AP_EARG;
    memset(t,0,sizeof(*t));t->io=*io;return atm_tx_stop(t);
}
int atm_tx_clear(struct atm_tx *t)
{
#if ADDA_TM_TX_ENABLED
    uint32_t status,diag;int rc=atm_tx_status(t,&status,&diag);
    if(rc<0)return rc;
    if(status&193u)return AP_EBUSY; /* owner, STOP recovery, peripheral reset */
    if(wr(t,8,1u)<0)return AP_EREMOTE;
    t->io.barrier(t->io.context);
    rc=atm_tx_status(t,&status,&diag);if(rc<0)return rc;
    if((status&1u) || !(status&2u) || (status&4u))return AP_EBUSY;
    t->pending=t->stopping=0u;return AP_OK;
#else
    (void)t;return ATM_TX_DISABLED;
#endif
}
int atm_tx_send(struct atm_tx *t,const struct aps_state *s,uint32_t now)
{
#if ADDA_TM_TX_ENABLED
    uint8_t burst[ATM_BUFFER_BYTES];uint32_t status,diag;unsigned i;int rc;
    if(!t || !s)return AP_EARG;
    if(t->pending || t->stopping)return AP_EBUSY;
    rc=atm_tx_status(t,&status,&diag);if(rc<0)return rc;
    if(status&197u)return AP_EBUSY;
    rc=atm_burst(s,t->sequence,now,burst,sizeof(burst));if(rc<0)return rc;
    if(rc*8>4096 || rc!=(int)ATM_BURST_BYTES)return AP_ELENGTH;
    rc=atm_tx_clear(t);if(rc<0)return rc;
    for(i=0;i<ATM_BURST_BYTES/4u;++i)if(wr(t,12,atm_word(burst,ATM_BURST_BYTES,i))<0){(void)atm_tx_stop(t);return AP_EREMOTE;}
    if(wr(t,16,ATM_BURST_BYTES*8u)<0){(void)atm_tx_stop(t);return AP_EREMOTE;}
    t->io.barrier(t->io.context);
    if(wr(t,20,1u)<0){(void)atm_tx_stop(t);return AP_EREMOTE;}
    t->io.barrier(t->io.context);t->pending=1u;t->started_ms=now;++t->sequence;return AP_OK;
#else
    (void)t;(void)s;(void)now;return ATM_TX_DISABLED;
#endif
}
int atm_tx_poll(struct atm_tx *t,unsigned ready,uint32_t now)
{
#if ADDA_TM_TX_ENABLED
    uint32_t status,diag;int rc;(void)ready;
    if(!t)return AP_EARG;
    if(!t->pending && !t->stopping)return AP_OK;
    rc=atm_tx_status(t,&status,&diag);if(rc<0)return rc;
    if(status&128u){t->stopping=2u;return AP_PENDING;}
    if(t->stopping==2u)return atm_tx_stop(t);
    if(t->stopping){if(!(status&65u)){t->stopping=t->pending=0u;}return AP_OK;}
    if(status&4u)return atm_tx_stop(t);
    if(!(status&1u) && (status&8u)){t->pending=0u;return AP_OK;}
    if((uint32_t)(now-t->started_ms)>=100u)return atm_tx_stop(t);
    return AP_PENDING;
#else
    (void)t;(void)ready;(void)now;return ATM_TX_DISABLED;
#endif
}
