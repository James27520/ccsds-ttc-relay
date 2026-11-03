#include "relay_doppler.h"
#include <math.h>
#include <string.h>

static int s12(unsigned v) { v &= 4095u; return v>=2048u?(int)v-4096:(int)v; }
uint32_t rd_word(double hz, double fs)
{ return (uint32_t)(int64_t)llround(hz*4294967296.0/fs); }
double rd_hz(uint32_t word, double fs)
{ return (word>=0x80000000u?(double)word-4294967296.0:(double)word)*fs/4294967296.0; }
int rd_measure(const uint32_t *iq, size_t n, double fs, double nominal,
               struct rd_measurement *m)
{
    double zr[RD_LAG]={0}, zi[RD_LAG]={0}, re=0, im=0, e0=0, e1=0, power=0;
    size_t k;
    if(!m) return -1;
    memset(m,0,sizeof(*m));
    if(!iq || n<=RD_LAG || !isfinite(fs) || fs<=0 || !isfinite(nominal) ||
       fabs(nominal)+60000.>=fs/2 || fs/(4.*RD_LAG)<=60000.) return -1;
    for(k=0;k<n;++k) {
        double i=s12(iq[k]), q=s12(iq[k]>>16), r=i*i-q*q, j=2*i*q;
        unsigned h=(unsigned)(k%RD_LAG);
        power+=i*i+q*q;
        if(fabs(i)>=2047 || fabs(q)>=2047) ++m->clipped;
        if(k>=RD_LAG) {
            re+=r*zr[h]+j*zi[h]; im+=j*zr[h]-r*zi[h];
            e0+=r*r+j*j; e1+=zr[h]*zr[h]+zi[h]*zi[h];
        }
        zr[h]=r; zi[h]=j;
    }
    m->rms=sqrt(power/n);
    if(e0<=0 || e1<=0) return 0;
    m->coherence=hypot(re,im)/sqrt(e0*e1);
    if(m->coherence>1) m->coherence=1;
    m->cfo_hz=atan2(im,re)*fs/(4.*3.14159265358979323846*RD_LAG);
    /* Lag 32 reduces short-lag quantization bias. Resolve its 480 kHz
     * ambiguity with the nominal IF; the allowed CFO is only +/-60 kHz. */
    m->cfo_hz+=round((nominal-m->cfo_hz)/(fs/(2.*RD_LAG)))*(fs/(2.*RD_LAG));
    m->cfo_hz-=nominal;
    m->valid=m->rms>=8 && m->clipped*1000u<=n &&
        m->coherence>=.85 && fabs(m->cfo_hz)<=60000.;
    return 0;
}
void rd_init(struct rd_channel *s, unsigned ch)
{
    struct dp_config c;
    memset(s,0,sizeof(*s)); dp_defaults(&c,2,ch);
    c.max_rate_hz_s=1000.; c.min_quality=.85; c.fresh_ms=500;
    c.hold_ms=2000; c.observation_max_age_ms=20;
    (void)dp_init(&s->incoming,&c); (void)dp_init(&s->outgoing,&c);
}
int rd_configure(struct rd_channel *s, uint32_t now, uint32_t ttl,
    double in_rf, double out_rf, double rx_lo, double tx_lo,
    double vi, double ai, double vo, double ao, uint32_t ddc, uint32_t duc)
{
    struct rd_channel next=*s;
    struct dp_prediction in, out;
    double nominal=in_rf-rx_lo, expected=tx_lo+nominal+rd_hz(duc,RD_FS)-rd_hz(ddc,RD_FS);
    double r[3]={700000,0,0}, v[3]={vi,0,0}, a[3]={ai,0,0};
    /* Independent RF legs; the output plan must match the existing relay.
     * No LO or lease is changed by this operation. */
    if(!isfinite(in_rf) || !isfinite(out_rf) || !isfinite(rx_lo) || !isfinite(tx_lo) ||
       in_rf<1980100000. || in_rf>2009900000. || out_rf<2170100000. || out_rf>2199900000. ||
       fabs(nominal)>900000. || fabs(expected-out_rf)>100. ||
       !ttl || ttl>300000u) return -1;
    in.start_ms=out.start_ms=now; in.duration_ms=out.duration_ms=ttl;
    in.rf_hz=in_rf; out.rf_hz=out_rf;
    if(dp_geometry(in_rf,r,v,a,&in.cfo_hz,&in.rate_hz_s)) return -1;
    v[0]=vo; a[0]=ao;
    if(dp_geometry(out_rf,r,v,a,&out.cfo_hz,&out.rate_hz_s)) return -1;
    if(dp_set_prediction(&next.incoming,&in) || dp_set_prediction(&next.outgoing,&out)) return -1;
    dp_set_mode(&next.incoming,DP_FUSION); dp_set_mode(&next.outgoing,DP_PREDICTION);
    next.nominal_if_hz=nominal; next.base_ddc=ddc; next.base_duc=duc;
    next.last_ddc=ddc; next.enabled=1; *s=next; return 0;
}
int rd_observe(struct rd_channel *s,const struct rd_measurement *m,
               uint32_t capture,uint32_t now,uint32_t seq)
{
    struct dp_observation o;
    if(!s->enabled) return -1;
    memset(&o,0,sizeof(o)); o.link=s->incoming.config.link;
    o.channel=s->incoming.config.channel; o.capture_ms=capture; o.sequence=seq;
    o.residual_hz=m->cfo_hz; o.quality=m->coherence; o.source_valid=m->valid;
    return dp_observe(&s->incoming,&o,now);
}
int rd_step(struct rd_channel *s,uint32_t now,unsigned leased,uint32_t *word,
            struct dp_output *in,struct dp_output *out)
{
    memset(in,0,sizeof(*in)); memset(out,0,sizeof(*out)); *word=s->base_ddc;
    if(!s->enabled) return 0;
    if(!leased || dp_plan(&s->incoming,now,in) || !in->valid ||
       dp_plan(&s->outgoing,now,out) || !out->valid) {
        s->enabled=0; dp_set_mode(&s->incoming,DP_OFF); dp_set_mode(&s->outgoing,DP_OFF);
        s->last_ddc=*word; return -1;
    }
    /* DDC multiplies exp(-j*phase). Positive incoming/outgoing Doppler
     * therefore requires a POSITIVE DDC increment. Keep DUC unchanged. */
    *word=s->base_ddc+rd_word(in->total_hz+out->total_hz,RD_FS);
    s->last_ddc=*word; return 1;
}
