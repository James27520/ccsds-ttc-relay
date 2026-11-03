#include "adda_controller.h"
#include "waveform_fixture.h"
#include <stdio.h>
#include <string.h>
static uint32_t now(struct act_controller *c){return c->clock.now_ms(c->clock.context);}
static void log_text(struct act_controller *c,const char *s)
{if(c->core->io.log)c->core->io.log(c->core->io.context,s);}
void act_init(struct act_controller *c,struct aps_state *s,struct ac_capture *a,const struct act_clock *clock)
{memset(c,0,sizeof(*c));c->core=s;c->capture=a;if(clock)c->clock=*clock;c->reported_state=AC_IDLE;
#if ADDA_DOPPLER_ENABLED
 {struct dp_config cfg;dp_defaults(&cfg,ADP_TC_LINK,0);(void)dp_init(&c->doppler,&cfg);}
#endif
}
static int decode(struct act_controller *c)
{
    struct ap_frame_result frame;adda_demod_stats stats;int rc;uint32_t start;char text[180];
    struct ac_capture *a=c->capture;
    if(!a || a->state!=AC_READY || !a->valid || c->consumed)return AP_EARG;
    if(c->core->transaction.pending)return AP_EBUSY;
    start=now(c);
#if ADDA_DOPPLER_ENABLED
    if(c->doppler.mode!=DP_OFF && ac_normal_ready(a) && (a->select&1u)==0) {
        rc=adp_receive(&c->doppler,a->samples,TC_SAMPLE_COUNT,a->arm_ms,start,
                       (uint32_t)(a->done_ms-a->arm_ms)+1u,a->snapshot.epoch,
                       &frame,&stats,&c->doppler_trace);
        /* Integer Hz log avoids requiring float printf in a standalone BSP.
         * Full-precision trace remains in RAM for the offline test harness. */
        (void)snprintf(text,sizeof(text),
          "DOPPLER t=%lu seq=%lu state=%u plan=%d used=%u pred=%ld residual=%ld applied=%ld rate=%ld obs=%d crc=%u\r\n",
          (unsigned long)a->arm_ms,(unsigned long)a->snapshot.epoch,
          (unsigned)c->doppler_trace.plan.state,c->doppler_trace.plan_result,c->doppler_trace.planned,
          (long)c->doppler_trace.plan.prediction_hz,(long)c->doppler_trace.plan.residual_hz,
          (long)c->doppler_trace.applied_correction_hz,(long)c->doppler_trace.applied_rate_hz_s,
          c->doppler_trace.observation_result,c->doppler_trace.crc_ok);
        log_text(c,text);
    } else
#endif
    rc=adda_receive(a->samples,TC_SAMPLE_COUNT,&frame,&stats);
    (void)snprintf(text,sizeof(text),"WAVEFORM_DECODE source=%s epoch=%lu rc=%d elapsed_ms=%lu\r\n",
      ac_normal_ready(a)?"ADC_NORMAL":"ADC_TEST",(unsigned long)a->snapshot.epoch,rc,(unsigned long)(now(c)-start));
    log_text(c,text);c->consumed=1u;
    if(rc!=1)return rc==0?AP_ENOFRAME:AP_EARG;
    if(c->filter) {
        if(!ac_normal_ready(a))return AP_EARG;
        rc=c->filter(c->filter_context,&frame,now(c));
        if(rc!=AP_OK)return rc;
    }
    /* This instant is intentionally not the start time of the slow decoder. */
    return aps_accept_decoded(c->core,&frame,ac_normal_ready(a)?APS_ADC_NORMAL:APS_ADC_TEST,now(c));
}
int act_waveformtest(struct act_controller *c)
{
    static const uint8_t expected[AP_BODY_BYTES]={1u,0x64u,0u,0x92u,9u,0u,0x77u,0xabu};
    struct ap_frame_result frame;adda_demod_stats stats;uint32_t start;int rc,pass;char text[180];
    if(!c || !c->clock.now_ms || !c->core)return AP_EARG;
    if(c->core->transaction.pending)return AP_EBUSY;
    start=now(c);rc=adda_receive(waveform_fixture,WAVEFORM_FIXTURE_COUNT,&frame,&stats);
    pass=rc==1 && !memcmp(frame.body,expected,AP_BODY_BYTES) &&
      frame.command.rx_mhz==WAVEFORM_FIXTURE_RX_MHZ && frame.command.tx_mhz==WAVEFORM_FIXTURE_TX_MHZ &&
      frame.command.seq==WAVEFORM_FIXTURE_SEQ;
    (void)snprintf(text,sizeof(text),"WAVEFORMTEST_%s source=SYNTHETIC samples=%u rx=100 tx=2450 seq=0 elapsed_ms=%lu no_UDP=1\r\n",
      pass?"PASS":"FAIL",WAVEFORM_FIXTURE_COUNT,(unsigned long)(now(c)-start));
    log_text(c,text);
    /* No call to accept_decoded, begin_command, or transport, even if armed. */
    return pass?AP_OK:AP_ECRC;
}
void act_poll(struct act_controller *c)
{
    char text[160];struct ac_capture *a;int rc;
    if(!c || !c->core || !c->clock.now_ms)return;
    aps_poll(c->core,now(c));a=c->capture;if(!a)return;
    ac_poll(a,now(c));
    if(c->reported_state!=a->state) {
        (void)snprintf(text,sizeof(text),"CAPTURE state=%u valid=%u error=%s epoch=%lu copied_words=%lu\r\n",
          (unsigned)a->state,a->valid,ac_error_name(a->error),(unsigned long)a->epoch,(unsigned long)a->copied_words);
        log_text(c,text);c->reported_state=a->state;
    }
    if(!c->automatic)return;
    if(!c->core->armed || !c->core->network_ready) {
        c->automatic=0u;log_text(c,"AUTO_STOP forwarding disarmed or network unavailable\r\n");return;
    }
    if(a->state==AC_ERROR){c->automatic=0u;log_text(c,"AUTO_STOP capture fault; explicit retry required\r\n");return;}
    if(c->core->transaction.pending || ac_busy(a))return;
    if(a->state==AC_READY && !c->consumed) {
        rc=decode(c);
        if(rc!=AP_OK && rc!=AP_ENOFRAME && rc!=AP_DUPLICATE) {
            c->automatic=0u;log_text(c,"AUTO_STOP decode/control error\r\n");
        }
        return;
    }
    rc=ac_start(a,TC_MODE_NORMAL,0u,0u,now(c));
    if(rc==AC_OK)c->consumed=0u;
    else {c->automatic=0u;log_text(c,"AUTO_STOP capture start rejected\r\n");}
}
int act_command_line(struct act_controller *c,const char *line)
{
    char op[24],arg[24],extra;unsigned ch,k;int fields,rc;char text[180];
    const char *guard;
    if(!c || !c->core || !c->clock.now_ms || !line)return AP_EARG;
    if(strlen(line)>127u)return AP_ELENGTH;
#if ADDA_DOPPLER_ENABLED
    if(!strncmp(line,"doppler ",8u)) {
        double frequency,rate;unsigned ttl;struct dp_prediction model;
        struct dp_output plan;enum dp_mode mode;
        if(!strcmp(line,"doppler status")) {
            int result=dp_plan(&c->doppler,now(c),&plan);
            (void)snprintf(text,sizeof(text),"DOPPLER_STATUS mode=%u state=%u rc=%d valid=%u accepted=%lu rejected=%lu\r\n",
              (unsigned)c->doppler.mode,(unsigned)plan.state,result,plan.valid,
              (unsigned long)c->doppler.accepted,(unsigned long)c->doppler.rejected);
            log_text(c,text);return AP_OK;
        }
        if(!strcmp(line,"doppler off")) {
            (void)dp_set_mode(&c->doppler,DP_OFF);return AP_OK;
        }
        /* Model/mode changes require an idle capture; they never start service
         * or arm forwarding, and no old observation survives a new model. */
        if(c->automatic || c->filter || (c->capture && ac_busy(c->capture))) return AP_EBUSY;
        if(sscanf(line,"doppler model %lf %lf %u %c",&frequency,&rate,&ttl,&extra)==3) {
            model.start_ms=now(c);model.duration_ms=ttl;model.rf_hz=ADP_TC_RF_HZ;
            model.cfo_hz=frequency;model.rate_hz_s=rate;
            return dp_set_prediction(&c->doppler,&model)==DP_OK?AP_OK:AP_EARG;
        }
        if(sscanf(line,"doppler radial %lf %lf %u %c",&frequency,&rate,&ttl,&extra)==3) {
            /* Input is radial range rate/acceleration in m/s and m/s^2.
             * Positive = receding; conversion runs here on the A9. This is
             * a local segment, not an on-board orbit propagator. */
            double r[3]={1,0,0},v[3]={frequency,0,0},a[3]={rate,0,0};
            model.start_ms=now(c);model.duration_ms=ttl;model.rf_hz=ADP_TC_RF_HZ;
            if(dp_geometry(model.rf_hz,r,v,a,&model.cfo_hz,&model.rate_hz_s)!=DP_OK) return AP_EARG;
            return dp_set_prediction(&c->doppler,&model)==DP_OK?AP_OK:AP_EARG;
        }
        if(!strcmp(line,"doppler predict")) mode=DP_PREDICTION;
        else if(!strcmp(line,"doppler measure")) mode=DP_MEASUREMENT;
        else if(!strcmp(line,"doppler hybrid")) mode=DP_FUSION;
        else return AP_EARG;
        if(mode!=DP_MEASUREMENT && !c->doppler.model_valid) return AP_EARG;
        return dp_set_mode(&c->doppler,mode)==DP_OK?AP_OK:AP_EARG;
    }
#endif
    guard=line;while(*guard==' ' || *guard=='\t')++guard;
    if(!strncmp(guard,"remotenettest",13u) &&
       (c->automatic || c->filter || c->core->armed || (c->capture && ac_busy(c->capture))))return AP_EBUSY;
    if(!strcmp(line,"waveformtest"))return act_waveformtest(c);
    if(!strcmp(line,"decode"))return decode(c);
    if(!strcmp(line,"capture cancel")) {
        c->automatic=0u;if(!c->capture)return AP_EARG;
        ac_cancel(c->capture,now(c));return AP_OK;
    }
    fields=sscanf(line,"%23s %23s %u %u %c",op,arg,&ch,&k,&extra);
    if(fields>=1 && !strcmp(op,"capture")) {
        if((fields!=2 && fields!=4) || (strcmp(arg,"training")!=0 && strcmp(arg,"normal")!=0))return AP_EARG;
        if(fields==2){ch=0u;k=0u;}
        if(!c->capture || c->core->transaction.pending || c->automatic)return AP_EBUSY;
        rc=ac_start(c->capture,!strcmp(arg,"normal")?TC_MODE_NORMAL:TC_MODE_TRAINING,ch,k,now(c));
        if(rc==AC_OK)c->consumed=0u;
        (void)snprintf(text,sizeof(text),"CAPTURE_REQUEST mode=%s channel=%u k=%u rc=%d\r\n",arg,ch,k,rc);log_text(c,text);
        return rc==AC_OK?AP_OK:AP_EARG;
    }
    if(!strcmp(line,"auto on")) {
        if(!c->capture || !c->core->network_ready || ac_probe(c->capture)!=AC_OK)return AP_EBUSY;
        c->automatic=1u;c->consumed=1u;
        (void)aps_command_line(c->core,"arm on",now(c));
        log_text(c,"AUTO_ON validated ADC_NORMAL captures only\r\n");return AP_OK;
    }
    if(!strcmp(line,"auto off")) {
        c->automatic=0u;(void)aps_command_line(c->core,"arm off",now(c));
        log_text(c,"AUTO_OFF\r\n");return AP_OK;
    }
    if(!strcmp(line,"status")) {
        (void)snprintf(text,sizeof(text),"CONTROLLER auto=%u capture_state=%u capture_valid=%u consumed=%u\r\n",
          c->automatic,c->capture?(unsigned)c->capture->state:0u,c->capture?c->capture->valid:0u,c->consumed);log_text(c,text);
    }
    if(!strcmp(line,"help"))log_text(c,"capture training/normal [CHANNEL K] | capture cancel | decode | auto on/off | waveformtest (SYNTHETIC)\r\n");
    return aps_command_line(c->core,line,now(c));
}
