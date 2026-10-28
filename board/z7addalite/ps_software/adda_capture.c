#include "adda_capture.h"
#include <string.h>

static int rd(struct ac_capture *s,uint32_t off,uint32_t *v)
{return s->io.read32(s->io.context,TC_CTRL_BASE+off,v)==0;}
static int wr(struct ac_capture *s,uint32_t off,uint32_t v)
{return s->io.write32(s->io.context,TC_CTRL_BASE+off,v)==0;}
static void barrier(struct ac_capture *s){s->io.barrier(s->io.context);}
static uint8_t byte_at(const uint32_t d[4],unsigned b)
{return (uint8_t)(d[b/4u]>>(8u*(b%4u)));}
static int diag_valid(const struct ac_capture *s,const uint32_t d[4],uint32_t mode)
{
    uint8_t at=mode==TC_MODE_NORMAL?0u:s->policy.a_test;
    uint8_t bt=mode==TC_MODE_NORMAL?0u:s->policy.b_test;
    return byte_at(d,TC_DIAG_BYTE_ID)==0x82u &&
      (byte_at(d,TC_DIAG_BYTE_A_FORMAT)&0x17u)==0x05u &&
      (byte_at(d,TC_DIAG_BYTE_B_FORMAT)&0x17u)==0x05u &&
      (byte_at(d,TC_DIAG_BYTE_A_TEST)&0x8fu)==at &&
      (byte_at(d,TC_DIAG_BYTE_B_TEST)&0x8fu)==bt &&
      (byte_at(d,TC_DIAG_BYTE_CLOCK_DIVIDE)&0x3fu)==0u &&
      (byte_at(d,TC_DIAG_BYTE_CLOCK_PHASE)&0xa0u)==0u &&
      (byte_at(d,TC_DIAG_BYTE_DCO_DELAY)&0x9fu)==0u &&
      (byte_at(d,TC_DIAG_BYTE_A_INDEX)&3u)==1u &&
      (byte_at(d,TC_DIAG_BYTE_B_INDEX)&3u)==2u &&
      byte_at(d,TC_DIAG_BYTE_ERROR)==0u &&
      byte_at(d,TC_DIAG_BYTE_CHECK_COUNT)==10u &&
      byte_at(d,TC_DIAG_BYTE_RESULT)==0xa1u &&
      byte_at(d,TC_DIAG_BYTE_VARIANT)==0x7du && (d[3]&0xffff0000u)==0u;
}
static int command(struct ac_capture *s,uint32_t value)
{
    uint32_t result;
    barrier(s);
    if(!wr(s,TC_REG_COMMAND,value))return 0;
    barrier(s);
    return rd(s,TC_REG_LAST_COMMAND_RESULT,&result) && result==TC_RESULT_ACCEPTED;
}
static void fail(struct ac_capture *s,enum ac_error error)
{s->valid=0u;s->error=error;s->state=AC_ERROR;}
void ac_init(struct ac_capture *s,const struct ac_io *io,const struct ac_policy *p,
             int16_t *samples,size_t capacity)
{
    memset(s,0,sizeof(*s));if(io)s->io=*io;if(p)s->policy=*p;
    s->samples=samples;s->capacity=capacity;s->state=AC_IDLE;
}
int ac_busy(const struct ac_capture *s)
{return s && s->state>=AC_CONFIG && s->state<=AC_RELEASING;}
int ac_probe(struct ac_capture *s)
{
    uint32_t v;
    static const uint32_t offsets[]={TC_REG_MAGIC,TC_REG_ABI_VERSION,TC_REG_SAMPLE_COUNT,
      TC_REG_SAMPLE_FORMAT,TC_REG_ADC_RATE_HZ,TC_REG_OUTPUT_RATE_HZ,TC_REG_CAPTURE_BYTES};
    static const uint32_t values[]={TC_MAGIC,TC_ABI_VERSION,TC_SAMPLE_COUNT,
      TC_SAMPLE_FORMAT,TC_ADC_RATE_HZ,TC_OUTPUT_RATE_HZ,TC_CAPTURE_BYTES};
    unsigned i;
    if(!s || !s->io.read32 || !s->io.write32 || !s->io.barrier || !s->samples ||
       s->capacity<TC_SAMPLE_COUNT || s->policy.build_id!=TC_FRAMEWORK_BUILD_ID ||
       s->policy.training_algorithm==TC_TRAIN_ALGO_NONE ||
       (s->policy.a_test&0x80u) || (s->policy.b_test&0x80u))return AC_EARG;
    for(i=0;i<sizeof(offsets)/sizeof(offsets[0]);++i) {
        if(!rd(s,offsets[i],&v))return AC_EBUS;
        if(v!=values[i])return AC_EIDENTITY;
    }
    if(!rd(s,TC_REG_FRAMEWORK_BUILD_ID,&v))return AC_EBUS;
    return v==s->policy.build_id?AC_OK:AC_EIDENTITY;
}
static int training_valid(const struct ac_capture *s,uint32_t v)
{
    return (v&TC_TRAINING_VALID) && !(v&TC_TRAINING_FAILED) &&
      ((v&TC_TRAINING_ALGORITHM_MASK)>>TC_TRAINING_ALGORITHM_SHIFT)==s->policy.training_algorithm &&
      (v>>TC_TRAINING_COUNT_SHIFT)>=TC_TRAINING_REQUIRED_VECTORS;
}
static int apply(struct ac_capture *s,uint32_t mode,uint32_t now)
{
    if(!rd(s,TC_REG_CONFIG_EPOCH,&s->config_epoch) || !wr(s,TC_REG_REQUEST_MODE,mode))return AC_EBUS;
    if(!command(s,TC_CMD_APPLY_MODE))return AC_ECOMMAND;
    s->configuring_mode=mode;s->phase_started_ms=now;s->state=AC_CONFIG;return AC_OK;
}
int ac_start(struct ac_capture *s,uint32_t mode,unsigned ch,unsigned k,uint32_t now)
{
    uint32_t status,training,last_epoch;int rc;
    if(!s || mode>TC_MODE_TRAINING || ch>1u || k>3u)return AC_EARG;
    if(ac_busy(s))return AC_EBUSY;
    rc=ac_probe(s);if(rc!=AC_OK){fail(s,(enum ac_error)rc);return rc;}
    if(!rd(s,TC_REG_STATUS,&status) || !rd(s,TC_REG_TRAINING_STATUS,&training) ||
       !rd(s,TC_REG_SNAPSHOT_EPOCH,&last_epoch)){fail(s,AC_EBUS);return AC_EBUS;}
    if((status&TC_STATUS_PHASE_MASK)!=TC_PHASE_IDLE)return AC_EBUSY;
    s->valid=0u;s->error=AC_OK;s->desired_mode=mode;s->select=ch|(k<<TC_SELECT_K_SHIFT);
    s->epoch=last_epoch+1u;if(!s->epoch)s->epoch=1u;
    rc=apply(s,mode==TC_MODE_NORMAL && training_valid(s,training)?TC_MODE_NORMAL:TC_MODE_TRAINING,now);
    if(rc!=AC_OK)fail(s,(enum ac_error)rc);
    return rc;
}
/* Read diagnostic with both config-busy and publication epoch fenced. Failure
 * attempts change the epoch too, so a torn failed bundle cannot be accepted. */
static int live_config(struct ac_capture *s,uint32_t *status,uint32_t *epoch,uint32_t *training)
{
    uint32_t end_epoch,end_status,active,d[4];unsigned i;
    if(!rd(s,TC_REG_STATUS,status) || !rd(s,TC_REG_CONFIG_EPOCH,epoch))return -1;
    if((*status&TC_STATUS_CONFIG_BUSY) || (*status&TC_STATUS_PHASE_MASK)!=TC_PHASE_IDLE)return 0;
    if(!rd(s,TC_REG_ACTIVE_MODE,&active) || !rd(s,TC_REG_TRAINING_STATUS,training))return -1;
    for(i=0;i<4u;++i)if(!rd(s,TC_REG_LIVE_DIAG0+4u*i,&d[i]))return -1;
    barrier(s);
    if(!rd(s,TC_REG_CONFIG_EPOCH,&end_epoch) || !rd(s,TC_REG_STATUS,&end_status))return -1;
    if(*epoch!=end_epoch || *status!=end_status)return 0;
    if(!*epoch || active!=(TC_ACTIVE_MODE_VALID|s->configuring_mode) ||
       !diag_valid(s,d,s->configuring_mode))return -2;
    return 1;
}
static int snapshot_read(struct ac_capture *s,struct ac_metadata *m)
{
    uint32_t status,err,epoch,training,active;unsigned i;
    const uint32_t ready=TC_STATUS_ADC_VERIFIED|TC_STATUS_TRAINING_VALID|TC_STATUS_STREAM_VALID|TC_STATUS_CLOCK_ALIVE;
    if(!rd(s,TC_REG_STATUS,&status) || !rd(s,TC_REG_CAPTURE_ERROR,&err))return 0;
    if((status&TC_STATUS_PHASE_MASK)!=TC_PHASE_DONE || err!=TC_ERROR_NONE ||
       (status&(TC_STATUS_CAPTURE_ERROR|TC_STATUS_CONFIG_BUSY)) || (status&ready)!=ready)return 0;
    if(!rd(s,TC_REG_ACTIVE_MODE,&active) || active!=(TC_ACTIVE_MODE_VALID|s->desired_mode))return 0;
#define GET(field,reg) if(!rd(s,reg,&m->field))return 0
    GET(epoch,TC_REG_SNAPSHOT_EPOCH);GET(select,TC_REG_SNAPSHOT_SELECT);
    GET(count,TC_REG_SAMPLE_COUNT);GET(written,TC_REG_SAMPLES_WRITTEN);
    GET(format,TC_REG_SAMPLE_FORMAT);GET(adc_hz,TC_REG_ADC_RATE_HZ);
    GET(output_hz,TC_REG_OUTPUT_RATE_HZ);GET(bytes,TC_REG_CAPTURE_BYTES);
    GET(config_epoch,TC_REG_SNAPSHOT_CONFIG_EPOCH);GET(flags,TC_REG_SNAPSHOT_FLAGS);
#undef GET
    for(i=0;i<4u;++i)if(!rd(s,TC_REG_SNAPSHOT_DIAG0+4u*i,&m->diag[i]))return 0;
    if(!rd(s,TC_REG_CONFIG_EPOCH,&epoch) || !rd(s,TC_REG_TRAINING_STATUS,&training))return 0;
    if(m->epoch!=s->epoch || m->config_epoch!=s->config_epoch || epoch!=s->config_epoch ||
       (m->select&~TC_SNAPSHOT_PARITY_MASK)!=s->select || m->count!=TC_SAMPLE_COUNT ||
       m->written!=TC_SAMPLE_COUNT || m->format!=TC_SAMPLE_FORMAT || m->adc_hz!=TC_ADC_RATE_HZ ||
       m->output_hz!=TC_OUTPUT_RATE_HZ || m->bytes!=TC_CAPTURE_BYTES || !training_valid(s,training) ||
       ((m->select&TC_SNAPSHOT_PARITY_MASK)!=0u)!=((training&TC_TRAINING_PARITY)!=0u))return 0;
    if(m->flags!=(TC_SNAPSHOT_TRAINING_VALID|TC_SNAPSHOT_CLOCK_ALIVE|TC_SNAPSHOT_CAPTURE_SUCCESS|
       (s->desired_mode==TC_MODE_NORMAL?TC_SNAPSHOT_NORMAL_VERIFIED:TC_SNAPSHOT_TRAINING_VERIFIED)))return 0;
    return diag_valid(s,m->diag,s->desired_mode);
}
static void release(struct ac_capture *s,uint32_t now)
{
    if(!command(s,TC_CMD_RELEASE)){fail(s,AC_ECOMMAND);return;}
    s->phase_started_ms=now;s->state=AC_RELEASING;
}
void ac_cancel(struct ac_capture *s,uint32_t now)
{
    uint32_t status,phase;
    if(!s || !s->io.read32 || !s->io.write32 || !s->io.barrier)return;
    s->valid=0u;s->error=AC_ECANCEL;
    /* Identity first; never write capture commands into an unrelated design. */
    if(ac_probe(s)!=AC_OK){fail(s,AC_EIDENTITY);return;}
    if(!rd(s,TC_REG_STATUS,&status)){fail(s,AC_EBUS);return;}
    phase=status&TC_STATUS_PHASE_MASK;
    if(phase==TC_PHASE_ARMING || phase==TC_PHASE_CAPTURING || phase==TC_PHASE_DRAINING) {
        if(!command(s,TC_CMD_ABORT)){fail(s,AC_ECOMMAND);return;}
        /* Poll subsequently observes FAILED before releasing; ABORT is async. */
        s->state=AC_CAPTURING;s->phase_started_ms=now;return;
    }
    if(phase==TC_PHASE_DONE || phase==TC_PHASE_FAILED){release(s,now);return;}
    if(phase==TC_PHASE_RELEASING){s->state=AC_RELEASING;s->phase_started_ms=now;return;}
    fail(s,AC_ECANCEL);
}
int ac_recover_cancel(struct ac_capture *s)
{
    uint32_t status;int rc;
    if(!s || s->state!=AC_ERROR || s->error!=AC_ECANCEL)return AC_EARG;
    rc=ac_probe(s);if(rc!=AC_OK)return rc;
    if(!rd(s,TC_REG_STATUS,&status))return AC_EBUS;
    if((status&TC_STATUS_PHASE_MASK)!=TC_PHASE_IDLE)return AC_EBUSY;
    s->state=AC_IDLE;s->error=AC_OK;s->valid=0;
    return AC_OK;
}
void ac_poll(struct ac_capture *s,uint32_t now)
{
    uint32_t status,phase,epoch,training,word,end,i;int rc;struct ac_metadata check;
    if(!s || !ac_busy(s))return;
    if(!rd(s,TC_REG_STATUS,&status)){fail(s,AC_EBUS);return;}
    phase=status&TC_STATUS_PHASE_MASK;
    if((uint32_t)(now-s->phase_started_ms)>=AC_TIMEOUT_MS){fail(s,AC_ETIMEOUT);return;}
    if(s->state==AC_CONFIG || s->state==AC_WAIT_READY) {
        if(s->state==AC_CONFIG) {
            if(!rd(s,TC_REG_CONFIG_EPOCH,&epoch)){fail(s,AC_EBUS);return;}
            if(epoch==s->config_epoch)return;
            s->state=AC_WAIT_READY;
        }
        rc=live_config(s,&status,&epoch,&training);
        if(rc<0){fail(s,rc==-1?AC_EBUS:AC_ECONFIG);return;}
        if(!rc)return;
        if(training&TC_TRAINING_FAILED){fail(s,AC_ETRAINING);return;}
        if(!training_valid(s,training) ||
           (status&(TC_STATUS_ADC_VERIFIED|TC_STATUS_TRAINING_VALID|TC_STATUS_STREAM_VALID|TC_STATUS_CLOCK_ALIVE))!=
             (TC_STATUS_ADC_VERIFIED|TC_STATUS_TRAINING_VALID|TC_STATUS_STREAM_VALID|TC_STATUS_CLOCK_ALIVE))return;
        if(s->configuring_mode!=s->desired_mode) {
            rc=apply(s,s->desired_mode,now);if(rc!=AC_OK)fail(s,(enum ac_error)rc);return;
        }
        s->config_epoch=epoch;
        if(!wr(s,TC_REG_REQUEST_SELECT,s->select) || !wr(s,TC_REG_REQUEST_EPOCH,s->epoch)) {fail(s,AC_EBUS);return;}
        if(!command(s,TC_CMD_ARM)){fail(s,AC_ECOMMAND);return;}
        s->state=AC_CAPTURING;s->phase_started_ms=now;return;
    }
    if(s->state==AC_CAPTURING) {
        if(phase==TC_PHASE_FAILED) {s->error=s->error==AC_ECANCEL?AC_ECANCEL:AC_ECAPTURE;release(s,now);return;}
        if(phase!=TC_PHASE_DONE)return;
        barrier(s);
        if(s->error==AC_ECANCEL){release(s,now);return;}
        if(!snapshot_read(s,&s->snapshot)){s->error=AC_EMETADATA;release(s,now);return;}
        s->copied_words=0u;s->state=AC_COPYING;s->phase_started_ms=now;
    }
    if(s->state==AC_COPYING) {
        if(!snapshot_read(s,&check) || memcmp(&check,&s->snapshot,sizeof(check))!=0) {
            s->error=AC_ERACE;release(s,now);return;
        }
        end=s->copied_words+AC_COPY_WORDS_PER_POLL;if(end>TC_WORD_COUNT)end=TC_WORD_COUNT;
        while(s->copied_words<end) {
            if(s->io.read32(s->io.context,TC_BRAM_BASE+4u*s->copied_words,&word)!=0){s->error=AC_EBUS;release(s,now);return;}
            for(i=0;i<2u;++i) {
                uint16_t raw=(uint16_t)(word>>(16u*i));
                uint16_t extension=(raw&0x2000u)?0xc000u:0u;
                int32_t signed_value=(raw&0x8000u)?(int32_t)raw-65536:(int32_t)raw;
                if((raw&0xc000u)!=extension){s->error=AC_ESAMPLE;release(s,now);return;}
                s->samples[2u*s->copied_words+i]=(int16_t)signed_value;
            }
            ++s->copied_words;
        }
        if(s->copied_words!=TC_WORD_COUNT)return;
        barrier(s);
        if(!snapshot_read(s,&check) || memcmp(&check,&s->snapshot,sizeof(check))!=0)s->error=AC_ERACE;
        release(s,now);return;
    }
    if(s->state==AC_RELEASING && phase==TC_PHASE_IDLE) {
        s->valid=s->error==AC_OK;s->state=s->valid?AC_READY:AC_ERROR;
    }
}
int ac_normal_ready(const struct ac_capture *s)
{return s && s->state==AC_READY && s->valid && s->desired_mode==TC_MODE_NORMAL;}
const char *ac_error_name(enum ac_error e)
{
    static const char *names[]={"OK","ARG","BUS","IDENTITY","BUSY","COMMAND","CONFIG","TRAINING",
      "TIMEOUT","CAPTURE","METADATA","RACE","SAMPLE","CANCEL"};
    return (unsigned)e<sizeof(names)/sizeof(names[0])?names[e]:"UNKNOWN";
}
