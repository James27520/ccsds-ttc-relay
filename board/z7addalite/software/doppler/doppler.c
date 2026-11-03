#include "doppler.h"
#include <math.h>
#include <string.h>

static int forward(uint32_t later, uint32_t earlier)
{ return (uint32_t)(later-earlier) < UINT32_C(0x80000000); }
static double limit(double x, double bound)
{ return x < -bound ? -bound : x > bound ? bound : x; }
static void forget(struct dp_tracker *s)
{ s->measured=0; s->residual_hz=0; s->residual_rate_hz_s=0; }
void dp_defaults(struct dp_config *c, uint32_t link, uint32_t channel)
{
    memset(c,0,sizeof(*c)); c->link=link; c->channel=channel;
    c->alpha=.3; c->beta=.04; c->max_shift_hz=60000.; c->max_rate_hz_s=250000.;
    c->max_residual_hz=8000.; c->max_residual_rate_hz_s=500.;
    c->innovation_hz=4000.; c->min_quality=.6;
    c->fresh_ms=1500; c->hold_ms=5000; c->observation_max_age_ms=1500;
}
int dp_init(struct dp_tracker *s, const struct dp_config *c)
{
    if(!s || !c) return DP_BAD_ARGUMENT;
    memset(s,0,sizeof(*s));
    if(!isfinite(c->alpha) || c->alpha<=0 || c->alpha>1 ||
       !isfinite(c->beta) || c->beta<0 || c->beta>1 ||
       !isfinite(c->max_shift_hz) || c->max_shift_hz<=0 ||
       !isfinite(c->max_rate_hz_s) || c->max_rate_hz_s<=0 ||
       !isfinite(c->max_residual_hz) || c->max_residual_hz<=0 ||
       !isfinite(c->max_residual_rate_hz_s) || c->max_residual_rate_hz_s<=0 ||
       !isfinite(c->innovation_hz) || c->innovation_hz<=0 ||
       !isfinite(c->min_quality) || c->min_quality<0 || c->min_quality>1 ||
       !c->fresh_ms || c->hold_ms<c->fresh_ms || c->hold_ms>600000u ||
       !c->observation_max_age_ms || c->observation_max_age_ms>c->hold_ms)
        return DP_BAD_ARGUMENT;
    s->config=*c; return DP_OK;
}
int dp_set_mode(struct dp_tracker *s, enum dp_mode mode)
{
    if(!s || (unsigned)mode>DP_FUSION || s->config.max_shift_hz<=0)
        return DP_BAD_ARGUMENT;
    if(s->mode!=mode || mode==DP_OFF) forget(s);
    s->mode=mode; return DP_OK;
}
int dp_set_prediction(struct dp_tracker *s, const struct dp_prediction *p)
{
    double end;
    if(!s || !p || !p->duration_ms || p->duration_ms>600000u ||
       !isfinite(p->rf_hz) || p->rf_hz<=0 || !isfinite(p->cfo_hz) ||
       !isfinite(p->rate_hz_s) || fabs(p->rate_hz_s)>s->config.max_rate_hz_s)
        return DP_BAD_ARGUMENT;
    end=p->cfo_hz+p->rate_hz_s*(p->duration_ms*.001);
    if(fabs(p->cfo_hz)>s->config.max_shift_hz || fabs(end)>s->config.max_shift_hz)
        return DP_BAD_ARGUMENT;
    /* A changed model must not inherit a residual from a different baseline. */
    s->prediction=*p; s->model_valid=1; forget(s); return DP_OK;
}
static int predict(const struct dp_tracker *s, uint32_t t, double *f, double *rate)
{
    *f=0; *rate=0;
    if(s->mode==DP_MEASUREMENT) return DP_OK;
    if(!s->model_valid || !forward(t,s->prediction.start_ms) ||
       (uint32_t)(t-s->prediction.start_ms)>=s->prediction.duration_ms)
        return DP_EXPIRED;
    *f=s->prediction.cfo_hz+s->prediction.rate_hz_s*((uint32_t)(t-s->prediction.start_ms)*.001);
    *rate=s->prediction.rate_hz_s; return DP_OK;
}
int dp_plan(const struct dp_tracker *s, uint32_t t, struct dp_output *o)
{
    uint32_t age=0;
    if(!s || !o) return DP_BAD_ARGUMENT;
    memset(o,0,sizeof(*o)); o->state=DP_DISABLED;
    if(s->mode==DP_OFF) return DP_OK;
    o->state=DP_FAULT;
    if(predict(s,t,&o->prediction_hz,&o->rate_hz_s)!=DP_OK) return DP_EXPIRED;
    o->state=s->mode==DP_MEASUREMENT?DP_MEASURE_ONLY:DP_PREDICT_ONLY;
    if(s->mode!=DP_PREDICTION && s->measured && forward(t,s->measurement_ms)) {
        age=t-s->measurement_ms; o->measurement_age_ms=age;
        if(age<=s->config.hold_ms) {
            /* Extrapolate only while fresh; a lost observation freezes its
             * residual at the fresh boundary, then discards it at hold expiry. */
            uint32_t advance=age>s->config.fresh_ms?s->config.fresh_ms:age;
            o->residual_hz=s->residual_hz+s->residual_rate_hz_s*(advance*.001);
            if(age<=s->config.fresh_ms) o->rate_hz_s+=s->residual_rate_hz_s;
            o->state=age>s->config.fresh_ms?DP_HOLD:
                s->mode==DP_MEASUREMENT?DP_MEASURE_ONLY:DP_HYBRID;
        } else if(s->mode==DP_MEASUREMENT) {o->state=DP_FAULT; return DP_EXPIRED;}
    } else if(s->mode==DP_MEASUREMENT) {o->state=DP_FAULT; return DP_EXPIRED;}
    o->total_hz=o->prediction_hz+o->residual_hz;
    if(!isfinite(o->total_hz) || fabs(o->total_hz)>s->config.max_shift_hz ||
       fabs(o->rate_hz_s)>s->config.max_rate_hz_s ||
       fabs(o->residual_hz)>(s->mode==DP_MEASUREMENT?s->config.max_shift_hz:s->config.max_residual_hz)) {
        o->state=DP_FAULT; return DP_OUTLIER;
    }
    o->correction_hz=-o->total_hz; o->valid=1; return DP_OK;
}
int dp_observe(struct dp_tracker *s, const struct dp_observation *m, uint32_t now)
{
    double prediction, rate, raw, residual, error, dt;
    int rc=DP_OK;
    if(!s || !m) return DP_BAD_ARGUMENT;
    if(s->mode==DP_OFF || !isfinite(m->residual_hz) || !isfinite(m->applied_correction_hz) ||
       !isfinite(m->quality) || m->quality<0 || m->quality>1) rc=DP_BAD_ARGUMENT;
    else if(m->link!=s->config.link || m->channel!=s->config.channel) rc=DP_WRONG_LINK;
    else if(!m->source_valid || m->quality<s->config.min_quality) rc=DP_QUALITY;
    else if(!forward(now,m->capture_ms) || now-m->capture_ms>s->config.observation_max_age_ms)
        rc=DP_EXPIRED;
    else if(s->measured && (!forward(m->capture_ms,s->measurement_ms) ||
            m->capture_ms==s->measurement_ms || !forward(m->sequence,s->sequence) || m->sequence==s->sequence))
        rc=DP_ORDER;
    if(rc==DP_OK) rc=predict(s,m->capture_ms,&prediction,&rate);
    if(rc!=DP_OK) {++s->rejected;return rc;}
    /* Observation can be before correction (applied=0), or after an additive
     * NCO correction. Undo the latter exactly once to avoid self-chasing. */
    raw=m->residual_hz-m->applied_correction_hz;
    residual=raw-prediction;
    if(fabs(raw)>s->config.max_shift_hz ||
       fabs(residual)>(s->mode==DP_MEASUREMENT?s->config.max_shift_hz:s->config.max_residual_hz)) {
        ++s->rejected;return DP_OUTLIER;
    }
    dt=(uint32_t)(m->capture_ms-s->measurement_ms)*.001;
    if(!s->measured || (uint32_t)(m->capture_ms-s->measurement_ms)>s->config.hold_ms) {
        s->residual_hz=residual; s->residual_rate_hz_s=0;
    } else {
        double advance=dt>s->config.fresh_ms*.001?s->config.fresh_ms*.001:dt;
        double prior=s->residual_hz+s->residual_rate_hz_s*advance;
        error=residual-prior;
        if(fabs(error)>s->config.innovation_hz) {++s->rejected;return DP_OUTLIER;}
        s->residual_hz=limit(prior+s->config.alpha*error,
                             s->mode==DP_MEASUREMENT?s->config.max_shift_hz:s->config.max_residual_hz);
        s->residual_rate_hz_s=limit(s->residual_rate_hz_s+s->config.beta*error/dt,
                                    s->config.max_residual_rate_hz_s);
    }
    s->measurement_ms=m->capture_ms; s->sequence=m->sequence; s->measured=1;
    ++s->accepted; return DP_OK;
}
int dp_geometry(double rf, const double r[3], const double v[3], const double a[3],
                double *f, double *rate)
{
    double rr=0,rv=0,vv=0,ra=0,distance,radial,acceleration; unsigned i;
    if(!r || !v || !a || !f || !rate || !isfinite(rf) || rf<=0) return DP_BAD_ARGUMENT;
    for(i=0;i<3;++i) {
        if(!isfinite(r[i]) || !isfinite(v[i]) || !isfinite(a[i])) return DP_BAD_ARGUMENT;
        rr+=r[i]*r[i];rv+=r[i]*v[i];vv+=v[i]*v[i];ra+=r[i]*a[i];
    }
    distance=sqrt(rr);
    if(!isfinite(distance) || distance<1 || !isfinite(rv) || !isfinite(vv) || !isfinite(ra))
        return DP_BAD_ARGUMENT;
    radial=rv/distance;acceleration=(vv+ra-radial*radial)/distance;
    *f=-rf*radial/299792458.;*rate=-rf*acceleration/299792458.;
    return isfinite(*f) && isfinite(*rate)?DP_OK:DP_BAD_ARGUMENT;
}
