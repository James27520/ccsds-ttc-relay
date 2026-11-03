#include "doppler.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned checks;
#define CHECK(x) do {++checks;if(!(x)){fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x);exit(1);}}while(0)
#define CLOSE(x,y) CHECK(fabs((x)-(y))<1e-7)
static struct dp_tracker tracker(enum dp_mode mode,uint32_t start)
{
    struct dp_tracker s;struct dp_config cfg;
    struct dp_prediction p={start,10000,100500000,2000,20};
    dp_defaults(&cfg,1,0);CHECK(dp_init(&s,&cfg)==DP_OK);
    CHECK(s.mode==DP_OFF);CHECK(dp_set_prediction(&s,&p)==DP_OK);
    CHECK(dp_set_mode(&s,mode)==DP_OK);return s;
}
int main(void)
{
    struct dp_tracker s=tracker(DP_FUSION,1000),other=tracker(DP_FUSION,1000),before;
    struct dp_output o;struct dp_observation m={1,0,1100,1,2502,0,1,1};
    struct dp_prediction p;struct dp_config c;double f,rate;
    double r[3]={700000,0,0},v[3]={7500,0,0},a[3]={0,0,0};
    CHECK(dp_geometry(100500000,r,v,a,&f,&rate)==DP_OK);CHECK(f<0);CLOSE(rate,0);
    CLOSE(f,-100500000.*7500/299792458.);
    v[0]=-7500;CHECK(dp_geometry(100500000,r,v,a,&f,&rate)==DP_OK);CHECK(f>0);
    v[0]=0;v[1]=7500;CHECK(dp_geometry(100500000,r,v,a,&f,&rate)==DP_OK);CLOSE(f,0);CHECK(rate<0);
    r[0]=0;CHECK(dp_geometry(1,r,v,a,&f,&rate)==DP_BAD_ARGUMENT);
    r[0]=NAN;CHECK(dp_geometry(1,r,v,a,&f,&rate)==DP_BAD_ARGUMENT);
    CHECK(dp_plan(&s,1100,&o)==DP_OK && o.state==DP_PREDICT_ONLY);CLOSE(o.total_hz,2002);
    CHECK(dp_observe(&s,&m,1200)==DP_OK);CHECK(s.accepted==1);
    CHECK(dp_plan(&s,1100,&o)==DP_OK && o.state==DP_HYBRID);CLOSE(o.residual_hz,500);CLOSE(o.correction_hz,-2502);
    CHECK(dp_plan(&other,1100,&o)==DP_OK && o.state==DP_PREDICT_ONLY);CLOSE(o.residual_hz,0);
    /* Post-correction observation must be reconstructed once, not added twice. */
    m.capture_ms=1200;m.sequence=2;m.residual_hz=4;m.applied_correction_hz=-2500;
    CHECK(dp_observe(&s,&m,1300)==DP_OK);CLOSE(s.residual_hz,500);
    before=s;CHECK(dp_observe(&s,&m,1300)==DP_ORDER);CLOSE(s.residual_hz,before.residual_hz);
    m.capture_ms=1199;m.sequence=3;CHECK(dp_observe(&s,&m,1300)==DP_ORDER);
    m.capture_ms=1300;m.channel=1;CHECK(dp_observe(&s,&m,1400)==DP_WRONG_LINK);
    m.channel=0;m.link=2;CHECK(dp_observe(&s,&m,1400)==DP_WRONG_LINK);
    m.link=1;m.source_valid=0;CHECK(dp_observe(&s,&m,1400)==DP_QUALITY);
    m.source_valid=1;m.quality=.5;CHECK(dp_observe(&s,&m,1400)==DP_QUALITY);
    m.quality=NAN;CHECK(dp_observe(&s,&m,1400)==DP_BAD_ARGUMENT);
    m.quality=1;CHECK(dp_observe(&s,&m,1299)==DP_EXPIRED);
    CHECK(dp_observe(&s,&m,3000)==DP_EXPIRED);
    m.residual_hz=70000;m.applied_correction_hz=0;CHECK(dp_observe(&s,&m,1400)==DP_OUTLIER);
    m.residual_hz=7506;CHECK(dp_observe(&s,&m,1400)==DP_OUTLIER);
    CLOSE(s.residual_hz,before.residual_hz);CHECK(s.measurement_ms==1200);
    CHECK(dp_plan(&s,2800,&o)==DP_OK && o.state==DP_HOLD);CLOSE(o.residual_hz,500);
    CHECK(dp_plan(&s,6201,&o)==DP_OK && o.state==DP_PREDICT_ONLY);CLOSE(o.residual_hz,0);
    CHECK(dp_plan(&s,11000,&o)==DP_EXPIRED && !o.valid && o.state==DP_FAULT);
    CHECK(dp_plan(&s,999,&o)==DP_EXPIRED && !o.valid);
    CHECK(dp_set_mode(&s,DP_OFF)==DP_OK);CHECK(!s.measured);
    CHECK(dp_plan(&s,1200,&o)==DP_OK && !o.valid && o.state==DP_DISABLED);
    CHECK(dp_observe(&s,&m,1400)==DP_BAD_ARGUMENT);
    CHECK(dp_set_mode(&s,DP_FUSION)==DP_OK);CHECK(!s.measured);
    p=s.prediction;p.cfo_hz=NAN;CHECK(dp_set_prediction(&s,&p)==DP_BAD_ARGUMENT);
    p=s.prediction;p.duration_ms=0;CHECK(dp_set_prediction(&s,&p)==DP_BAD_ARGUMENT);
    p=s.prediction;p.rate_hz_s=100000;CHECK(dp_set_prediction(&s,&p)==DP_BAD_ARGUMENT);
    p=s.prediction;p.cfo_hz=1000;CHECK(dp_set_prediction(&s,&p)==DP_OK);CHECK(!s.measured);
    s=tracker(DP_FUSION,UINT32_MAX-1000u);
    m=(struct dp_observation){1,0,UINT32_MAX-500u,UINT32_MAX,2510,0,1,1};
    CHECK(dp_observe(&s,&m,UINT32_MAX-400u)==DP_OK);
    m.capture_ms=99;m.sequence=0;m.residual_hz=2522;
    CHECK(dp_observe(&s,&m,100)==DP_OK);CHECK(dp_plan(&s,100,&o)==DP_OK && o.valid);
    CHECK(o.measurement_age_ms==1);
    s=tracker(DP_MEASUREMENT,1000);CHECK(dp_plan(&s,1100,&o)==DP_EXPIRED);
    m=(struct dp_observation){1,0,1100,1,2500,0,1,1};CHECK(dp_observe(&s,&m,1200)==DP_OK);
    CHECK(dp_plan(&s,1100,&o)==DP_OK && o.state==DP_MEASURE_ONLY);CLOSE(o.total_hz,2500);
    CHECK(dp_plan(&s,6101,&o)==DP_EXPIRED && !o.valid);
    dp_defaults(&c,1,0);c.alpha=NAN;CHECK(dp_init(&s,&c)==DP_BAD_ARGUMENT && s.mode==DP_OFF);
    dp_defaults(&c,1,0);c.hold_ms=0;CHECK(dp_init(&s,&c)==DP_BAD_ARGUMENT);
    printf("PASS doppler state/geometry: %u checks; tracker=%u bytes\n",checks,(unsigned)sizeof(s));
    return 0;
}
