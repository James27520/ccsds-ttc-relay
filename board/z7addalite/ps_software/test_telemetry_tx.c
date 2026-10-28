#include "adda_telemetry_tx.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
struct mock { unsigned reads,writes,words,sends,stops,clears,barriers;uint32_t status,magic,abi,length,data[128]; };
static int read_reg(void *c,uint32_t address,uint32_t *v)
{
    struct mock *m=c;unsigned off=address-ATM_TX_BASE;++m->reads;
    switch(off){case 0:*v=m->status;break;case 4:*v=0;break;case 0x1c:*v=m->magic;break;case 0x20:*v=m->abi;break;case 0x30:*v=0x102a0100;break;case 0x34:*v=3;break;default:return -1;}return 0;
}
static int write_reg(void *c,uint32_t address,uint32_t v)
{
    struct mock *m=c;unsigned off=address-ATM_TX_BASE;++m->writes;
    assert(!(m->status&128u));
    switch(off){case 8:assert(!(m->status&65u));m->words=0;m->status=2;++m->clears;break;
    case 12:assert(m->words<128);m->data[m->words++]=v;break;
    case 16:m->length=v;break;case 20:assert(v==1 && m->length<=m->words*32);m->status=3;++m->sends;break;
    case 24:assert(v==1);m->status=4;++m->stops;break;default:return -1;}return 0;
}
static void barrier(void *c){++((struct mock *)c)->barriers;}
static struct aps_command_record record(uint32_t event,enum aps_origin origin,uint8_t seq,uint16_t rx,uint16_t tx)
{struct aps_command_record r;memset(&r,0,sizeof(r));r.valid=1;r.event=event;r.origin=origin;r.command.seq=seq;r.command.rx_mhz=rx;r.command.tx_mhz=tx;return r;}
int main(int argc,char **argv)
{
    struct aps_state s;struct atm_tx tx;struct mock m;struct atm_io io;
    uint8_t p[96],frame[101],burst[512],bad[96];unsigned i;int n;
    (void)argv;memset(&s,0,sizeof(s));s.network_ready=s.armed=s.transaction.pending=1;
    s.telemetry_events=9;s.decoded_frames=4;s.applied_commands=2;s.failed_transactions=1;
    s.last_decoded=record(9,APS_SYNTHETIC,201,900,1000);
    s.last_send.record=record(7,APS_ADC_NORMAL,199,800,950);
    s.last_send.transaction_seq=0x1234;s.last_send.count=3;s.last_send.rc=-2;
    s.last_ack.record=record(8,APS_UART_NETTEST,198,700,900);
    s.last_ack.reply.seq=0xabcd;s.last_ack.reply.rx_hz=700000001;s.last_ack.reply.tx_hz=899999998;
    assert(atm_pack(&s,7,1234,p,sizeof(p))==96);
    if(argc>1){for(i=0;i<sizeof(p);++i)printf("%02x",p[i]);puts("");return 0;}
    assert(!memcmp(p,"ATM1\1\77\0\0",8));assert(p[11]==7 && p[14]==4 && p[15]==0xd2);
    assert(p[36]==3 && p[46]==1 && p[64]==4 && p[70]==0xab && p[71]==0xcd);
    assert(p[56]==0xff && p[59]==0xfe && p[75]==0);
    memset(bad,0x5a,sizeof(bad));assert(atm_pack(&s,7,1234,bad,95)==AP_ELENGTH);assert(bad[0]==0x5a);
    s.last_ack.reply.rc=-1;assert(atm_pack(&s,7,1234,bad,96)==AP_EARG);s.last_ack.reply.rc=0;
    assert(atm_frame(p,sizeof(p),frame,sizeof(frame))==101);
    assert(frame[0]==0xaa && frame[2]==96 && ap_crc16(frame+3,96)==((unsigned)frame[99]<<8|frame[100]));
    n=atm_burst(&s,7,1234,burst,sizeof(burst));assert(n==420);
    for(i=0;i<4;++i)assert(!memcmp(burst+8+i*101,frame,101));
    assert(atm_word(burst,420,0)==0xaaaaaaaau);assert(atm_word(burst,420,2)==0xaaaa6041u);
    assert(atm_word(burst,420,105)==0);assert(atm_word(burst,420,128)==0);
    memset(&m,0,sizeof(m));m.status=2;m.magic=ATM_TX_MAGIC;m.abi=1;
    io.context=&m;io.read32=read_reg;io.write32=write_reg;io.barrier=barrier;
#if ADDA_TM_TX_ENABLED
    assert(atm_tx_init(&tx,&io)==0 && m.stops==1);
    {uint32_t cfg,diag;assert(atm_tx_configuration(&tx,&cfg,&diag)==0 && cfg==3 && diag==0x102a0100);}
    assert(atm_tx_send(&tx,&s,0)==AP_EBUSY);assert(atm_tx_poll(&tx,1,0)==0);
    assert(atm_tx_send(&tx,&s,0)==AP_EBUSY);assert(atm_tx_clear(&tx)==0);
    s.network_ready=0; /* Explicit telemetry reports network-off state too. */
    assert(atm_tx_send(&tx,&s,100)==0);assert(m.words==105 && m.length==3360 && m.sends==1);
    assert(m.data[2]==0xaaaa6041u);assert(atm_tx_send(&tx,&s,101)==AP_EBUSY);
    {unsigned before=m.writes;assert(atm_tx_clear(&tx)==AP_EBUSY);assert(m.writes==before);}
    assert(atm_tx_poll(&tx,0,101)==AP_PENDING && m.stops==1);
    assert(atm_tx_stop(&tx)==0 && m.stops==2);assert(atm_tx_poll(&tx,0,102)==0 && !tx.pending);
    assert(atm_tx_send(&tx,&s,103)==AP_EBUSY);assert(atm_tx_clear(&tx)==0);
    assert(atm_tx_send(&tx,&s,UINT32_MAX-10)==0);
    assert(atm_tx_poll(&tx,1,90)==0 && m.stops==3);assert(atm_tx_poll(&tx,1,91)==0);
    assert(atm_tx_clear(&tx)==0);
    assert(atm_tx_send(&tx,&s,200)==0);m.status=8; /* consumed: READY=0 */
    assert(atm_tx_poll(&tx,0,700)==0 && !tx.pending && tx.sequence==3 && m.stops==3);
    assert(atm_tx_send(&tx,&s,701)==0 && m.sends==4); /* clear restores READY */
    m.status=8;assert(atm_tx_poll(&tx,0,735)==0);
    m.magic=0;assert(atm_tx_send(&tx,&s,800)==AP_EMISMATCH);assert(m.sends==4);
    memset(&m,0,sizeof(m));m.magic=ATM_TX_MAGIC;m.abi=1;m.status=128u;
    assert(atm_tx_init(&tx,&io)==AP_PENDING && m.writes==0);
    assert(atm_tx_poll(&tx,0,1)==AP_PENDING && m.writes==0);
    assert(atm_tx_clear(&tx)==AP_EBUSY && m.writes==0);
    assert(atm_tx_send(&tx,&s,1)==AP_EBUSY && m.writes==0);
    m.status=2;assert(atm_tx_poll(&tx,0,2)==AP_OK && m.stops==1);
    m.status=68; /* owner released, but STOP acknowledgment still draining */
    {unsigned before=m.writes;
     assert(atm_tx_poll(&tx,0,3)==AP_OK && tx.stopping);
     assert(atm_tx_clear(&tx)==AP_EBUSY && m.writes==before);}
    m.status=4;assert(atm_tx_poll(&tx,0,4)==AP_OK && !tx.stopping);
    assert(atm_tx_clear(&tx)==AP_OK);assert(atm_tx_send(&tx,&s,5)==AP_OK);
#else
    assert(atm_tx_init(&tx,&io)==ATM_TX_DISABLED);assert(atm_tx_send(&tx,&s,0)==ATM_TX_DISABLED);
    assert(atm_tx_stop(&tx)==ATM_TX_DISABLED);assert(atm_tx_poll(&tx,0,0)==ATM_TX_DISABLED);
    assert(atm_tx_clear(&tx)==ATM_TX_DISABLED);
    {uint32_t status,diag;assert(atm_tx_status(&tx,&status,&diag)==ATM_TX_DISABLED);}
    {uint32_t cfg,diag;assert(atm_tx_configuration(&tx,&cfg,&diag)==ATM_TX_DISABLED);}
    assert(m.reads==0 && m.writes==0 && m.barriers==0);
#endif
    puts("PASS telemetry serialization, bounded burst and opt-in MMIO mocks; no hardware execution");return 0;
}
