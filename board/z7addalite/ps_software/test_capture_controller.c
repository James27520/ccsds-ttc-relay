#include "adda_controller.h"
#include "waveform_fixture.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned checks;
#define CHECK(x) do{++checks;if(!(x)){fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
struct model {
    uint32_t r[32],ms,words,reads,writes,barriers,commands,mode_changes,arm_count,release_count;
    unsigned fault_read,fault_write,bad_config,reject_command,stuck_release,skip_config_epoch;
    unsigned corrupt_sample,race_word,stop_clock_word,synthetic_words,sends;
    uint8_t packet[26];char last_log[256];
};
static int16_t samples[TC_SAMPLE_COUNT];
static struct model model;
static struct ac_capture cap;
static struct aps_state core;
static struct act_controller ctrl;
static void set_diag(struct model *m,uint32_t mode)
{
    uint8_t d[16]={0x82,5,5,0,0,0,0,0,1,2,0,10,0xa1,0x7d,0,0};unsigned i;
    if(mode==TC_MODE_TRAINING){d[3]=6;d[4]=4;}
    if(m->bad_config)d[0]=0;
    for(i=0;i<4u;++i)m->r[(TC_REG_LIVE_DIAG0/4u)+i]=(uint32_t)d[4u*i]|((uint32_t)d[4u*i+1u]<<8)|
      ((uint32_t)d[4u*i+2u]<<16)|((uint32_t)d[4u*i+3u]<<24);
}
static void finish_capture(struct model *m)
{m->r[TC_REG_STATUS/4]=(m->r[TC_REG_STATUS/4]&~TC_STATUS_PHASE_MASK)|TC_PHASE_DONE;m->r[TC_REG_SAMPLES_WRITTEN/4]=TC_SAMPLE_COUNT;m->r[TC_REG_SNAPSHOT_FLAGS/4]|=TC_SNAPSHOT_CAPTURE_SUCCESS;}
static int read32(void *ctx,uint32_t addr,uint32_t *v)
{
    struct model *m=ctx;uint32_t i;++m->reads;if(m->fault_read)return -1;
    if(addr>=TC_BRAM_BASE && addr<TC_BRAM_BASE+TC_CAPTURE_BYTES) {
        i=(addr-TC_BRAM_BASE)/4u;++m->words;
        if(m->race_word && m->words==m->race_word)++m->r[TC_REG_SNAPSHOT_EPOCH/4];
        if(m->stop_clock_word && m->words==m->stop_clock_word)m->r[TC_REG_STATUS/4]&=~TC_STATUS_CLOCK_ALIVE;
        *v=m->synthetic_words?(uint32_t)(uint16_t)waveform_fixture[2u*i]|((uint32_t)(uint16_t)waveform_fixture[2u*i+1u]<<16):UINT32_C(0xe0001fff);
        if(m->corrupt_sample && !i)*v=UINT32_C(0x00002000);
        return 0;
    }
    CHECK(addr>=TC_CTRL_BASE && addr<=TC_CTRL_BASE+TC_REG_FRAMEWORK_BUILD_ID && !(addr&3u));
    *v=m->r[(addr-TC_CTRL_BASE)/4u];return 0;
}
static int write32(void *ctx,uint32_t addr,uint32_t v)
{
    struct model *m=ctx;uint32_t off=addr-TC_CTRL_BASE;unsigned i;++m->writes;
    if(m->fault_write)return -1;
    CHECK(!(addr&3u) && addr>=TC_CTRL_BASE && addr<TC_CTRL_BASE+TC_CTRL_RANGE);
    if(off!=TC_REG_COMMAND) {CHECK(off==TC_REG_REQUEST_MODE || off==TC_REG_REQUEST_EPOCH || off==TC_REG_REQUEST_SELECT);m->r[off/4]=v;return 0;}
    ++m->commands;m->r[TC_REG_LAST_COMMAND_RESULT/4]=m->reject_command?TC_RESULT_BAD_STATE:TC_RESULT_ACCEPTED;
    if(m->reject_command)return 0;
    if(v==TC_CMD_APPLY_MODE) {
        ++m->mode_changes;if(!m->skip_config_epoch)++m->r[TC_REG_CONFIG_EPOCH/4];
        m->r[TC_REG_ACTIVE_MODE/4]=TC_ACTIVE_MODE_VALID|m->r[TC_REG_REQUEST_MODE/4];
        set_diag(m,m->r[TC_REG_REQUEST_MODE/4]);
        m->r[TC_REG_STATUS/4]=TC_STATUS_ADC_VERIFIED|TC_STATUS_TRAINING_VALID|TC_STATUS_STREAM_VALID|TC_STATUS_CLOCK_ALIVE;
        m->r[TC_REG_TRAINING_STATUS/4]=(128u<<16)|(TC_TRAIN_ALGO_PN9<<8)|TC_TRAINING_VALID;
    } else if(v==TC_CMD_ARM) {
        ++m->arm_count;m->words=0;m->r[TC_REG_STATUS/4]|=TC_PHASE_CAPTURING;
        m->r[TC_REG_SNAPSHOT_EPOCH/4]=m->r[TC_REG_REQUEST_EPOCH/4];
        m->r[TC_REG_SNAPSHOT_SELECT/4]=m->r[TC_REG_REQUEST_SELECT/4];
        m->r[TC_REG_SNAPSHOT_CONFIG_EPOCH/4]=m->r[TC_REG_CONFIG_EPOCH/4];
        m->r[TC_REG_SNAPSHOT_FLAGS/4]=TC_SNAPSHOT_TRAINING_VALID|TC_SNAPSHOT_CLOCK_ALIVE|
          ((m->r[TC_REG_REQUEST_MODE/4]==TC_MODE_NORMAL)?TC_SNAPSHOT_NORMAL_VERIFIED:TC_SNAPSHOT_TRAINING_VERIFIED);
        for(i=0;i<4u;++i)m->r[TC_REG_SNAPSHOT_DIAG0/4+i]=m->r[TC_REG_LIVE_DIAG0/4+i];
    } else if(v==TC_CMD_RELEASE) {
        ++m->release_count;
        m->r[TC_REG_STATUS/4]=(m->r[TC_REG_STATUS/4]&~(TC_STATUS_PHASE_MASK|TC_STATUS_CAPTURE_ERROR))|
          (m->stuck_release?TC_PHASE_RELEASING:TC_PHASE_IDLE);
        m->r[TC_REG_CAPTURE_ERROR/4]=0u;
    } else if(v==TC_CMD_ABORT) {
        m->r[TC_REG_STATUS/4]=(m->r[TC_REG_STATUS/4]&~TC_STATUS_PHASE_MASK)|TC_PHASE_FAILED;
        m->r[TC_REG_CAPTURE_ERROR/4]=TC_ERROR_ABORT;
    } else CHECK(0);
    return 0;
}
static void barrier_cb(void *ctx){++((struct model*)ctx)->barriers;}
static uint32_t now_ms(void *ctx){return ((struct model*)ctx)->ms++;}
static void log_cb(void *ctx,const char *s){struct model *m=ctx;(void)snprintf(m->last_log,sizeof(m->last_log),"%s",s);}
static int send_cb(void *ctx,uint32_t ip,uint16_t port,const uint8_t *b,size_t n)
{struct model *m=ctx;CHECK(ip==APS_RELAY_IPV4 && port==5005 && n==26u);++m->sends;memcpy(m->packet,b,n);return 0;}
static void setup(void)
{
    struct ac_io io={&model,read32,write32,barrier_cb};
    struct ac_policy p={TC_FRAMEWORK_BUILD_ID,TC_TRAIN_ALGO_PN9,6,4};
    struct aps_io net={&model,log_cb,send_cb};struct act_clock clock={&model,now_ms};
    memset(&model,0,sizeof(model));memset(samples,0x66,sizeof(samples));
    model.r[TC_REG_MAGIC/4]=TC_MAGIC;model.r[TC_REG_ABI_VERSION/4]=TC_ABI_VERSION;
    model.r[TC_REG_FRAMEWORK_BUILD_ID/4]=TC_FRAMEWORK_BUILD_ID;
    model.r[TC_REG_SAMPLE_COUNT/4]=TC_SAMPLE_COUNT;model.r[TC_REG_SAMPLE_FORMAT/4]=TC_SAMPLE_FORMAT;
    model.r[TC_REG_ADC_RATE_HZ/4]=TC_ADC_RATE_HZ;model.r[TC_REG_OUTPUT_RATE_HZ/4]=TC_OUTPUT_RATE_HZ;
    model.r[TC_REG_CAPTURE_BYTES/4]=TC_CAPTURE_BYTES;
    ac_init(&cap,&io,&p,samples,TC_SAMPLE_COUNT);aps_init(&core,&net);act_init(&ctrl,&core,&cap,&clock);
}
static void arm(uint32_t mode)
{
    unsigned i;CHECK(ac_start(&cap,mode,0,0,model.ms++)==AC_OK);
    for(i=0;i<10u && cap.state!=AC_CAPTURING;++i)ac_poll(&cap,model.ms++);
    CHECK(cap.state==AC_CAPTURING && model.arm_count==1u && !cap.valid);
}
static void drain(void)
{
    unsigned i;for(i=0;i<100u && ac_busy(&cap);++i)ac_poll(&cap,model.ms++);
    CHECK(!ac_busy(&cap));
}
int main(void)
{
    unsigned i,writes;uint32_t malformed_offsets[]={TC_REG_SAMPLE_COUNT,TC_REG_SAMPLES_WRITTEN,TC_REG_SAMPLE_FORMAT,
      TC_REG_ADC_RATE_HZ,TC_REG_OUTPUT_RATE_HZ,TC_REG_CAPTURE_BYTES,TC_REG_SNAPSHOT_EPOCH,TC_REG_SNAPSHOT_CONFIG_EPOCH,
      TC_REG_CONFIG_EPOCH,TC_REG_SNAPSHOT_SELECT,TC_REG_SNAPSHOT_FLAGS};
    setup();CHECK(model.writes==0 && !core.armed && !core.network_ready && !ctrl.automatic);
    CHECK(ac_probe(&cap)==AC_OK && model.writes==0);
    for(i=0;i<3u;++i) {uint32_t off=i==0?TC_REG_MAGIC:i==1?TC_REG_ABI_VERSION:TC_REG_FRAMEWORK_BUILD_ID;
      setup();model.r[off/4]^=1;CHECK(ac_start(&cap,TC_MODE_NORMAL,0,0,0)==AC_EIDENTITY && model.writes==0);}
    setup();cap.policy.training_algorithm=0;CHECK(ac_probe(&cap)==AC_EARG);
    setup();model.fault_read=1;CHECK(ac_start(&cap,0,0,0,0)==AC_EBUS && model.writes==0);
    setup();CHECK(ac_start(&cap,0,2,0,0)==AC_EARG && model.writes==0);
    setup();model.r[TC_REG_STATUS/4]=TC_PHASE_DONE;CHECK(ac_start(&cap,0,0,0,0)==AC_EBUSY && model.writes==0);
    setup();model.reject_command=1;CHECK(ac_start(&cap,0,0,0,0)==AC_ECOMMAND && !cap.valid);
    setup();model.bad_config=1;CHECK(ac_start(&cap,0,0,0,0)==AC_OK);ac_poll(&cap,1);CHECK(cap.state==AC_ERROR && cap.error==AC_ECONFIG && !model.arm_count);
    setup();model.skip_config_epoch=1;CHECK(ac_start(&cap,0,0,0,UINT32_MAX-10u)==AC_OK);ac_poll(&cap,AC_TIMEOUT_MS);CHECK(cap.error==AC_ETIMEOUT && !model.arm_count);
    setup();arm(TC_MODE_NORMAL);CHECK(model.mode_changes==2);finish_capture(&model);drain();
    CHECK(cap.state==AC_READY && ac_normal_ready(&cap) && model.words==TC_WORD_COUNT && model.release_count==1 && model.barriers>0);
    CHECK(samples[0]==8191 && samples[1]==-8192 && samples[TC_SAMPLE_COUNT-1]==-8192);
    setup();model.r[TC_REG_SNAPSHOT_EPOCH/4]=UINT32_MAX;arm(TC_MODE_TRAINING);CHECK(cap.epoch==1u && model.mode_changes==1);
    finish_capture(&model);drain();CHECK(cap.valid && !ac_normal_ready(&cap));
    for(i=0;i<sizeof(malformed_offsets)/sizeof(malformed_offsets[0]);++i) {
        setup();arm(TC_MODE_NORMAL);finish_capture(&model);model.r[malformed_offsets[i]/4]^=1u;drain();
        CHECK(!cap.valid && cap.error==AC_EMETADATA && model.words==0 && model.release_count==1);
    }
    for(i=0;i<14u;++i) {
        setup();arm(TC_MODE_NORMAL);finish_capture(&model);
        /* Flip a required bit in every diagnostic field (format bit0 etc.). */
        model.r[TC_REG_SNAPSHOT_DIAG0/4+i/4]^=(i==6?0x20u:1u)<<(8u*(i%4u));drain();
        CHECK(!cap.valid && cap.error==AC_EMETADATA && model.words==0);
    }
    setup();arm(0);finish_capture(&model);model.r[TC_REG_SNAPSHOT_DIAG3/4]|=0x10000u;drain();CHECK(!cap.valid);
    setup();arm(0);finish_capture(&model);model.r[TC_REG_CAPTURE_ERROR/4]=TC_ERROR_FIFO_OVERFLOW;drain();CHECK(!cap.valid && model.words==0);
    for(i=0;i<4u;++i) {
        setup();arm(0);finish_capture(&model);model.r[TC_REG_STATUS/4]&=~(TC_STATUS_ADC_VERIFIED<<i);
        drain();CHECK(!cap.valid && cap.error==AC_EMETADATA && model.words==0);
    }
    setup();arm(0);finish_capture(&model);model.r[TC_REG_STATUS/4]|=TC_STATUS_CONFIG_BUSY;drain();CHECK(!cap.valid && model.words==0);
    setup();arm(0);finish_capture(&model);model.r[TC_REG_ACTIVE_MODE/4]&=~TC_ACTIVE_MODE_VALID;drain();CHECK(!cap.valid && model.words==0);
    setup();arm(0);model.r[TC_REG_STATUS/4]=(model.r[TC_REG_STATUS/4]&~TC_STATUS_PHASE_MASK)|TC_PHASE_FAILED;drain();CHECK(!cap.valid && cap.error==AC_ECAPTURE);
    setup();arm(0);finish_capture(&model);model.corrupt_sample=1;drain();CHECK(cap.error==AC_ESAMPLE && !cap.valid);
    setup();arm(0);finish_capture(&model);model.race_word=TC_WORD_COUNT;drain();CHECK(cap.error==AC_ERACE && !cap.valid && model.words==TC_WORD_COUNT);
    setup();arm(0);finish_capture(&model);model.stop_clock_word=2;drain();CHECK(cap.error==AC_ERACE && !cap.valid && model.words==AC_COPY_WORDS_PER_POLL);
    setup();arm(0);finish_capture(&model);model.stuck_release=1;
    for(i=0;i<70u;++i)ac_poll(&cap,model.ms++);CHECK(cap.state==AC_RELEASING && !cap.valid);
    ac_poll(&cap,model.ms+AC_TIMEOUT_MS);CHECK(cap.state==AC_ERROR && cap.error==AC_ETIMEOUT && !cap.valid);
    setup();arm(0);ac_cancel(&cap,model.ms++);drain();CHECK(!cap.valid && cap.error==AC_ECANCEL && model.release_count==1);
    writes=model.writes;CHECK(ac_recover_cancel(&cap)==AC_OK && cap.state==AC_IDLE && !cap.valid && model.writes==writes);
    CHECK(ac_recover_cancel(&cap)==AC_EARG);
    setup();cap.state=AC_ERROR;cap.error=AC_ECANCEL;model.r[TC_REG_STATUS/4]=TC_PHASE_DONE;
    writes=model.writes;CHECK(ac_recover_cancel(&cap)==AC_EBUSY && cap.state==AC_ERROR && model.writes==writes);
    setup();cap.state=AC_ERROR;cap.error=AC_ECONFIG;CHECK(ac_recover_cancel(&cap)==AC_EARG && cap.error==AC_ECONFIG);
    setup();cap.state=AC_ERROR;cap.error=AC_ECANCEL;model.fault_read=1;
    CHECK(ac_recover_cancel(&cap)==AC_EBUS && cap.state==AC_ERROR);
    setup();CHECK(act_command_line(&ctrl,"auto on")==AP_EBUSY && !ctrl.automatic);
    CHECK(act_command_line(&ctrl,"capture normal 0 4")==AP_EARG);
    CHECK(act_command_line(&ctrl,"capture wrong")==AP_EARG);
    CHECK(act_command_line(&ctrl,"decode")==AP_EARG);
    aps_set_network_ready(&core,1);CHECK(act_command_line(&ctrl,"arm on")==AP_OK);
    CHECK(act_command_line(&ctrl,"waveformtest")==AP_OK && model.sends==0 && !core.applied_commands && !core.decoded_frames);
    CHECK(strstr(model.last_log,"source=SYNTHETIC") && strstr(model.last_log,"no_UDP=1"));
    setup();model.synthetic_words=1;arm(1);finish_capture(&model);drain();aps_set_network_ready(&core,1);core.armed=1;
    CHECK(act_command_line(&ctrl,"decode")==AP_OK && model.sends==0 && core.decoded_frames==1);
    CHECK(act_command_line(&ctrl,"decode")==AP_EARG);
    setup();model.synthetic_words=1;arm(0);finish_capture(&model);drain();aps_set_network_ready(&core,1);core.armed=1;
    CHECK(act_command_line(&ctrl,"decode")==AP_OK && model.sends==1 && core.transaction.pending && core.last_send_ms>=model.ms-1u);
    CHECK(act_command_line(&ctrl,"waveformtest")==AP_EBUSY && model.sends==1);
    CHECK(act_command_line(&ctrl,"auto off")==AP_OK && !core.armed && !core.transaction.pending);
    setup();aps_set_network_ready(&core,1);CHECK(act_command_line(&ctrl,"auto on")==AP_OK && ctrl.automatic && core.armed);
    act_poll(&ctrl);CHECK(model.mode_changes==1 && model.sends==0);
    CHECK(act_command_line(&ctrl,"auto off")==AP_OK && !ctrl.automatic);
    writes=model.writes;for(i=0;i<3;++i)act_poll(&ctrl);CHECK(model.sends==0 && model.writes>=writes);
    printf("PASS capture/controller %u assertions; mock buses only; synthetic decode never transmits unless deliberately modeled as validated normal snapshot\n",checks);
    return 0;
}
