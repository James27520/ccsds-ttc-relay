#include "adda_service.h"
#include <stdio.h>
#include <string.h>
static struct aps_state *core(struct asv_service *s){return s->controller->core;}
static int tx_ready(struct asv_service *s)
{
    uint32_t status,diag,flags,cfg;
    if(s->tx->stopping)return AP_EBUSY;
    if(atm_tx_status(s->tx,&status,&diag)<0 || diag || (status&197u))return AP_EBUSY;
    if(atm_tx_configuration(s->tx,&flags,&cfg)<0 || flags!=3u || (cfg>>28)!=1u)return AP_EMISMATCH;
    return AP_OK;
}
static int same(const struct aps_command_record *r,const struct ap_command *c)
{return r->valid && r->origin==APS_ADC_NORMAL && r->command.seq==c->seq &&
 r->command.rx_mhz==c->rx_mhz && r->command.tx_mhz==c->tx_mhz;}
static int filter(void *context,const struct ap_frame_result *frame,uint32_t now)
{
    struct asv_service *s=context;struct aps_state *c=core(s);struct ap_command command;
    unsigned byte,bit;
    if(!s->active || s->state!=ASV_LISTEN)return AP_EBUSY;
    if((uint32_t)(now-s->started_ms)>=ASV_LEASE_MS){(void)asv_stop(s,ASV_LEASE,now);return AP_EBUSY;}
    if(!c->network_ready){(void)asv_stop(s,ASV_NETWORK,now);return AP_EBUSY;}
    if(ap_body_parse(frame->body,AP_BODY_BYTES,&command)!=AP_OK)return AP_EARG;
    byte=command.seq>>3;bit=1u<<(command.seq&7u);
    if(s->used[byte]&bit)return AP_DUPLICATE;
    if(c->transaction.applied_valid && c->transaction.applied_command.seq==command.seq){
        /* Remember an inherited already-applied sequence too: observing old A,
         * then accepting B, must not allow A again within this service lease. */
        s->used[byte]|=(uint8_t)bit;++s->used_count;return AP_DUPLICATE;
    }
    if(s->accepted>=ASV_TRANSACTION_LIMIT){(void)asv_stop(s,ASV_LIMIT,now);return AP_EBUSY;}
    s->used[byte]|=(uint8_t)bit;++s->used_count;++s->accepted;
    s->command=command;s->baseline_applied=c->applied_commands;
    s->baseline_failures=c->failed_transactions;s->reply_sent=0;
    /* Critical ordering: no further capture/decode can overwrite d before ACK. */
    s->controller->automatic=0;s->state=ASV_WAIT_ACK;
    return AP_OK;
}
void asv_init(struct asv_service *s,struct act_controller *c,struct atm_tx *t)
{memset(s,0,sizeof(*s));s->controller=c;s->tx=t;}
int asv_start(struct asv_service *s,uint32_t now)
{
    struct aps_state *c;struct act_controller *a;
    if(!s || !s->controller || !s->tx || !s->controller->core)return AP_EARG;
    c=core(s);a=s->controller;
    if(s->active || s->state==ASV_STOPPING || a->automatic || a->filter ||
       !a->capture || ac_busy(a->capture) ||
       (a->capture->state==AC_ERROR && a->capture->error!=AC_ECANCEL) ||
       c->armed || c->transaction.pending || !c->network_ready ||
       c->rx_gain_db!=0u || c->tx_attenuation_db!=89u || s->tx->pending ||
       ac_probe(a->capture)!=AC_OK || tx_ready(s)!=AP_OK)return AP_EBUSY;
    if(a->capture->state==AC_ERROR && ac_recover_cancel(a->capture)!=AC_OK)return AP_EBUSY;
    memset(s->used,0,sizeof(s->used));s->accepted=s->completed=s->failed=s->reply_sent=s->used_count=0;
    memset(&s->command,0,sizeof(s->command));s->udp_seq=0;s->reply_seq=0;
    s->started_ms=now;s->ack_ms=s->last_reply_ms=0;s->reason=ASV_NONE;
    s->active=1;s->state=ASV_LISTEN;
    a->filter_context=s;a->filter=filter;a->consumed=1;a->automatic=1;c->armed=1;
    return AP_OK;
}
int asv_stop(struct asv_service *s,enum asv_reason reason,uint32_t now)
{
    struct act_controller *a;int rc;
    if(!s || !s->controller)return AP_EARG;
    if(!s->active)return AP_OK;
    a=s->controller;s->active=0;s->reason=(unsigned)reason;s->state=ASV_STOPPING;
    a->automatic=0;a->filter=0;a->filter_context=0;a->core->armed=0;
    ap_transaction_abort(&a->core->transaction);
    if(a->capture && ac_busy(a->capture))ac_cancel(a->capture,now);
    rc=atm_tx_stop(s->tx);
    return rc;
}
static void listen(struct asv_service *s,uint32_t now)
{
    if(s->accepted>=ASV_TRANSACTION_LIMIT){(void)asv_stop(s,ASV_LIMIT,now);return;}
    s->state=ASV_LISTEN;s->controller->consumed=1;
    s->controller->automatic=1;core(s)->armed=1;
}
void asv_poll(struct asv_service *s,uint32_t now)
{
    struct aps_state *c;uint32_t status,diag,age;int rc;
    if(!s || !s->controller || !s->tx)return;
    if(!s->active){
        if(s->state==ASV_STOPPING && !s->tx->pending && !s->tx->stopping &&
           (!s->controller->capture || !ac_busy(s->controller->capture)))s->state=ASV_OFF;
        return;
    }
    c=core(s);
    if((uint32_t)(now-s->started_ms)>=ASV_LEASE_MS){(void)asv_stop(s,ASV_LEASE,now);return;}
    if(!c->network_ready){(void)asv_stop(s,ASV_NETWORK,now);return;}
    if(atm_tx_status(s->tx,&status,&diag)<0 || diag || (status&196u) || s->tx->stopping){
        (void)asv_stop(s,ASV_TM,now);return;
    }
    if(s->state==ASV_LISTEN){
        if(s->controller->capture->state==AC_ERROR){(void)asv_stop(s,ASV_CAPTURE,now);return;}
        if(!s->controller->automatic){(void)asv_stop(s,ASV_DECODE,now);return;}
    } else if(s->state==ASV_WAIT_ACK){
        if(c->transaction.pending)return;
        if(c->applied_commands!=s->baseline_applied+1u || c->failed_transactions!=s->baseline_failures ||
           !same(&c->last_decoded,&s->command) || !same(&c->last_send.record,&s->command) ||
           !same(&c->last_ack.record,&s->command) || c->last_send.rc || c->last_ack.reply.rc ||
           c->last_send.transaction_seq!=c->last_ack.reply.seq ||
           !(c->last_decoded.event<c->last_send.record.event &&
             c->last_send.record.event<c->last_ack.record.event)){
            ++s->failed;s->reason=ASV_UDP;listen(s,now);return;
        }
        /* Disarm only after a completed ACK: arm-off before it would abort UDP. */
        c->armed=0;s->ack_ms=now;s->reply_seq=s->tx->sequence;
        s->udp_seq=c->last_ack.reply.seq;
        rc=atm_burst(c,s->reply_seq,now,s->burst,sizeof(s->burst));
        if(rc!=(int)ATM_BURST_BYTES){(void)asv_stop(s,ASV_TM,now);return;}
        s->state=ASV_DELAY;
    } else if(s->state==ASV_DELAY || s->state==ASV_REPLY){
        age=(uint32_t)(now-s->ack_ms);
        if(age<ASV_REPLY_DELAY_MS)return;
        age-=ASV_REPLY_DELAY_MS;
        /* Never start a burst which would overrun the absolute reply deadline.
         * A slow poll skips airtime; it never catches up or extends the window. */
        if(age>=ASV_REPLY_WINDOW_MS || (s->reply_sent>=ASV_REPLY_LIMIT && !s->tx->pending)){
            if(s->tx->pending){(void)asv_stop(s,ASV_TM,now);return;}
            if(!s->reply_sent){++s->failed;s->reason=ASV_TM;}
            else ++s->completed;
            listen(s,now);return;
        }
        if(age>ASV_REPLY_WINDOW_MS-34u || s->reply_sent>=ASV_REPLY_LIMIT || s->tx->pending)return;
        if(s->reply_sent && (uint32_t)(now-s->last_reply_ms)<ASV_REPLY_PERIOD_MS)return;
        if(tx_ready(s)!=AP_OK){(void)asv_stop(s,ASV_TM,now);return;}
        rc=atm_tx_send_burst(s->tx,s->burst,sizeof(s->burst),now);
        if(rc!=AP_OK){(void)asv_stop(s,ASV_TM,now);return;}
        if(!s->reply_sent)++s->tx->sequence;
        ++s->reply_sent;s->last_reply_ms=now;s->state=ASV_REPLY;
    }
}
int asv_status(const struct asv_service *s,uint32_t now,char *out,size_t size)
{
    uint32_t elapsed,left=0,reply_left=0;int n;
    if(!s || !out || !size)return AP_EARG;
    elapsed=(uint32_t)(now-s->started_ms);
    if(s->active && elapsed<ASV_LEASE_MS)left=ASV_LEASE_MS-elapsed;
    elapsed=(uint32_t)(now-s->ack_ms);
    if(s->active && (s->state==ASV_DELAY || s->state==ASV_REPLY) &&
       elapsed<ASV_REPLY_DELAY_MS+ASV_REPLY_WINDOW_MS)reply_left=ASV_REPLY_DELAY_MS+ASV_REPLY_WINDOW_MS-elapsed;
    n=snprintf(out,size,"SERVICE active=%u state=%u reason=%u remaining_ms=%lu accepted=%u completed=%u failed=%u air_seq=%u udp_seq=%u reply_seq=%lu reply_sent=%u reply_limit=%u reply_remaining_ms=%lu used=%u\r\n",
       s->active,s->state,s->reason,(unsigned long)left,s->accepted,s->completed,s->failed,
       (unsigned)s->command.seq,(unsigned)s->udp_seq,(unsigned long)s->reply_seq,
       s->reply_sent,ASV_REPLY_LIMIT,(unsigned long)reply_left,s->used_count);
    if(n<0 || (size_t)n>=size){out[0]=0;return AP_ELENGTH;}return n;
}
int asv_cancel_command(const char *line)
{return !strcmp(line,"network off") || !strcmp(line,"auto off") || !strcmp(line,"arm off") ||
 !strcmp(line,"capture cancel") || !strcmp(line,"tmstop") || !strcmp(line,"service off");}
int asv_command_allowed(const struct asv_service *s,const char *line)
{
    if(!s->active && s->state!=ASV_STOPPING)return 1;
    return asv_cancel_command(line) || !strcmp(line,"status") || !strcmp(line,"telemetry") ||
      !strcmp(line,"tmstatus") || !strcmp(line,"help") || !strcmp(line,"service status");
}
