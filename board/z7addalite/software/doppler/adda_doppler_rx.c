#include "adda_doppler_rx.h"
#include <math.h>
#include <string.h>
int adp_receive(struct dp_tracker *s,const int16_t *samples,size_t count,
                uint32_t capture,uint32_t now,uint32_t uncertainty,uint32_t seq,
                struct ap_frame_result *frame,adda_demod_stats *stats,struct adp_trace *tr)
{
    struct dp_output current,end; struct dp_observation obs; adda_demod_plan plan;
    size_t i; int rc; uint32_t duration;
    if(!s || !samples || !stats || !frame || !tr || count<65536 || count>262144) return -1;
    memset(tr,0,sizeof(*tr));tr->capture_ms=capture;tr->sequence=seq;
    tr->observation_result=DP_BAD_ARGUMENT;
    if(s->mode==DP_OFF) return adda_receive(samples,count,frame,stats);
    duration=(uint32_t)ceil(count/31250.0);
    tr->plan_result=dp_plan(s,capture,&tr->plan);
    if(s->config.link!=ADP_TC_LINK || s->config.channel!=0 ||
       (s->mode!=DP_MEASUREMENT && s->prediction.rf_hz!=ADP_TC_RF_HZ)) tr->plan_result=DP_WRONG_LINK;
    else if((uint32_t)(now-capture)>s->config.observation_max_age_ms || uncertainty>20u ||
            fabs(tr->plan.rate_hz_s)*uncertainty*.001>50.) tr->plan_result=DP_EXPIRED;
    else if(tr->plan_result==DP_OK && tr->plan.valid &&
            (dp_plan(s,now,&current)!=DP_OK || dp_plan(s,capture+duration,&end)!=DP_OK))
        tr->plan_result=DP_EXPIRED;
    if(tr->plan_result!=DP_OK) {tr->plan.valid=0;tr->plan.state=DP_FAULT;}
    if(tr->plan_result==DP_OK && tr->plan.valid && s->mode!=DP_MEASUREMENT) {
        plan.center_hz=ADP_TC_IF_HZ+tr->plan.total_hz;
        plan.rate_hz_s=tr->plan.rate_hz_s;
        plan.search_hz=s->mode==DP_PREDICTION?0:8000.;
        tr->planned=1;
        rc=adda_receive_planned(samples,count,frame,stats,&plan);
        tr->applied_rate_hz_s=-plan.rate_hz_s;
    } else rc=adda_receive(samples,count,frame,stats);
    tr->crc_ok=rc==1;
    if(stats->carrier_hz>0) {
        tr->measured_cfo_hz=stats->carrier_hz-ADP_TC_IF_HZ;
        tr->applied_correction_hz=-tr->measured_cfo_hz;
    }
    for(i=0;i<count;++i) if(samples[i]<=-8192 || samples[i]>=8191) ++tr->clipped_samples;
    /* Legacy static estimator is also the bootstrap for measurement-only.
     * In prediction-only, carrier_hz is imposed, NOT a measurement: never
     * feed it into the residual filter. Wrong/stale plans cannot update it. */
    if(s->mode==DP_PREDICTION ||
       (s->mode!=DP_MEASUREMENT && tr->plan_result!=DP_OK) ||
       s->config.link!=ADP_TC_LINK || s->config.channel!=0 ||
       uncertainty>20u || (uint32_t)(now-capture)>s->config.observation_max_age_ms)
        return rc;
    memset(&obs,0,sizeof(obs));obs.link=ADP_TC_LINK;obs.channel=0;
    obs.capture_ms=capture;obs.sequence=seq;obs.residual_hz=tr->measured_cfo_hz;
    /* The square-spectrum estimator observes raw ADC samples before the
     * mixer. Its carrier_hz already includes the prediction: subtract it only
     * inside dp_observe, and do NOT subtract the mixer correction again. */
    obs.applied_correction_hz=0;obs.source_valid=tr->crc_ok;
    obs.quality=rc==1 && stats->input_rms>=8 && tr->clipped_samples*1000u<=count?1.:0.;
    tr->observation_result=dp_observe(s,&obs,now);
    return rc;
}
