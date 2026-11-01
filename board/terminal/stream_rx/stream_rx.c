/* Text-blind experimental AAAA/LEN/payload/CRC16 receiver. See README.md. */
#define _POSIX_C_SOURCE 200809L
#ifdef _WIN32
#define _WIN32_WINNT 0x0600
#endif
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <signal.h>
#include <time.h>
#if defined(__ARM_NEON)
#include <arm_neon.h>
#endif
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#include <windows.h>
#else
#include <unistd.h>
#include <pthread.h>
#endif

#define PI 3.14159265358979323846
#define WIN 32768
#define HOP 28672
#define KEEP (WIN-HOP)
#define CFO_DECIM 4
#define CFO_FS (500000.0 / CFO_DECIM)
#define FFT_LOG2 14
#define FFT (1 << FFT_LOG2)
#define FIR 61
#define SPS 5
#define MF 41
#define MAXBITS (WIN/SPS+1)
#define MAXFRAMES (MAXBITS/48+1)
#define HISTORY 128
typedef struct { float r,i; } C;
typedef struct { unsigned char p[200]; int len,start,end; unsigned crc; } Frame;
typedef struct { Frame f[MAXFRAMES]; int count,rejects,complete; float eye; } Trial;
typedef struct { unsigned char p[200]; int len; unsigned crc; double cfo; uint64_t sample; } Message;
static C window[WIN], work[WIN], matched[WIN], spectrum[FFT], mixed_input[16384];
static float hann[WIN], lowpass[FIR], rrc[MF], mixr[14], mixi[14];
static C history[2*FIR];
static unsigned char bits[MAXBITS];
static unsigned reverse_bits[FFT];
static C twiddle[FFT];
static Message messages[HISTORY];
static int message_count,stdio_mode;
static uint64_t samples,clips,frames,rejects,windows,last_frame_end,decimated;
static double sumsq,max_decode_ms,last_decode_ms,last_cfo,started_ms;
static uint64_t pending_energy;
static double last_fft_ms,last_matched_ms,last_carrier_ms;
static double recent_rms;
static uint64_t recent_clips;
static int mixer_phase;
static const char *prefix;
static volatile sig_atomic_t stopping;
static int output_failed,input_error;
static double frontend_ms,decode_ms,fft_total_ms,carrier_total_ms,matched_total_ms,publish_ms,consumer_wait_ms;
static int live_mode;

/* Two MiB = 210 ms at 2.5 MSPS. One reader drains the pipe while the
   consumer decodes a window. A full queue applies bounded backpressure;
   it never discards a sample or grows without limit. DMA loss is unknown. */
#define BLOCK_BYTES 65536
#define QUEUE_BLOCKS 32
static unsigned char input_queue[QUEUE_BLOCKS][BLOCK_BYTES];
static size_t queue_lengths[QUEUE_BLOCKS];
static unsigned queue_head,queue_count,queue_high;
static uint64_t acquired_bytes,queue_bytes,backpressure_events;
static double read_ms,backpressure_ms;
static int reader_done,reader_error;
#ifdef _WIN32
static CRITICAL_SECTION queue_mutex;
static CONDITION_VARIABLE queue_cond;
static HANDLE reader_thread;
static void lock_queue(void) { EnterCriticalSection(&queue_mutex); }
static void unlock_queue(void) { LeaveCriticalSection(&queue_mutex); }
static void wake_queue(void) { WakeAllConditionVariable(&queue_cond); }
static void wait_queue(void) { SleepConditionVariableCS(&queue_cond,&queue_mutex,100); }
#else
static pthread_mutex_t queue_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t queue_cond=PTHREAD_COND_INITIALIZER;
static pthread_t reader_thread;
static void lock_queue(void) { pthread_mutex_lock(&queue_mutex); }
static void unlock_queue(void) { pthread_mutex_unlock(&queue_mutex); }
static void wake_queue(void) { pthread_cond_broadcast(&queue_cond); }
static void wait_queue(void) {
    struct timespec t;clock_gettime(CLOCK_REALTIME,&t);t.tv_nsec+=100000000;
    if(t.tv_nsec>=1000000000) {t.tv_nsec-=1000000000;t.tv_sec++;}
    pthread_cond_timedwait(&queue_cond,&queue_mutex,&t);
}
#endif

static double now_ms(void) {
#ifdef _WIN32
    LARGE_INTEGER t,f; QueryPerformanceCounter(&t); QueryPerformanceFrequency(&f);
    return 1000.0*(double)t.QuadPart/(double)f.QuadPart;
#else
    struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
    return (double)t.tv_sec*1000.0+t.tv_nsec/1e6;
#endif
}
static double cpu_ms(void) {
#ifdef _WIN32
    FILETIME a,b,k,u;ULARGE_INTEGER x,y;
    GetProcessTimes(GetCurrentProcess(),&a,&b,&k,&u);
    x.LowPart=k.dwLowDateTime;x.HighPart=k.dwHighDateTime;
    y.LowPart=u.dwLowDateTime;y.HighPart=u.dwHighDateTime;
    return (x.QuadPart+y.QuadPart)/10000.0;
#else
    struct timespec t;clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&t);
    return t.tv_sec*1000.0+t.tv_nsec/1e6;
#endif
}
#ifdef _WIN32
static DWORD WINAPI read_input(LPVOID unused) {
#else
static void *read_input(void *unused) {
#endif
    unsigned char block[BLOCK_BYTES];(void)unused;
    while(!stopping) {
        double mark=now_ms(),duration;size_t n=fread(block,1,sizeof(block),stdin);
        int bad=ferror(stdin),done=feof(stdin)||bad;duration=now_ms()-mark;
        lock_queue();read_ms+=duration;acquired_bytes+=n;
        if(queue_count==QUEUE_BLOCKS) {
            mark=now_ms();if(live_mode)backpressure_events++;
            while(queue_count==QUEUE_BLOCKS&&!stopping)wait_queue();
            backpressure_ms+=now_ms()-mark;
        }
        if(n&&!stopping) {
            unsigned slot=(queue_head+queue_count)%QUEUE_BLOCKS;
            memcpy(input_queue[slot],block,n);queue_lengths[slot]=n;queue_count++;queue_bytes+=n;
            if(queue_count>queue_high)queue_high=queue_count;
        }
        if(done||stopping) {reader_done=1;reader_error=bad;}
        wake_queue();unlock_queue();if(done)break;
    }
    lock_queue();reader_done=1;wake_queue();unlock_queue();
    return 0;
}
static size_t take_input(unsigned char *out) {
    size_t n=0;double mark=now_ms();lock_queue();
    while(!queue_count&&!reader_done&&!stopping)wait_queue();
    consumer_wait_ms+=now_ms()-mark;
    if(queue_count&&!stopping) {
        n=queue_lengths[queue_head];memcpy(out,input_queue[queue_head],n);
        queue_bytes-=n;queue_head=(queue_head+1)%QUEUE_BLOCKS;queue_count--;wake_queue();
    }
    unlock_queue();return n;
}
static void stop(int sig) { (void)sig; stopping=1; }
static unsigned crc16(const unsigned char *p,int n) {
    unsigned c=0xffff; int j;
    while(n--) { c^=(unsigned)*p++<<8; for(j=0;j<8;j++) c=(c&0x8000)?(c<<1)^0x1021:c<<1; c&=0xffff; }
    return c;
}
static void init(void) {
    int n,j,len; double norm=0,total=0;
    for(n=0;n<FIR;n++) {
        double x=n-(FIR-1)/2.0;
        double v=(x==0?0.08:sin(PI*.08*x)/(PI*x))*(.54-.46*cos(2*PI*n/(FIR-1)));
        lowpass[n]=(float)v; total+=v;
    }
    for(n=0;n<FIR;n++) lowpass[n]/=(float)total;
    for(n=0;n<MF;n++) {
        double t=(n-20)/5.0,b=.35,v;
        if(fabs(t)<1e-8) v=1-b+4*b/PI;
        else if(fabs(fabs(t)-1/(4*b))<1e-6)
            v=b/sqrt(2)*((1+2/PI)*sin(PI/(4*b))-(1-2/PI)*cos(PI/(4*b)));
        else v=(sin(PI*t*(1-b))+4*b*t*cos(PI*t*(1+b)))/(PI*t*(1-pow(4*b*t,2)));
        rrc[n]=(float)v; norm+=v*v;
    }
    for(n=0;n<MF;n++) rrc[n]/=(float)sqrt(norm);
    for(n=0;n<10;n++) { mixr[n]=(float)cos(2*PI*n/10); mixi[n]=(float)sin(2*PI*n/10); }
    for(n=10;n<14;n++) {mixr[n]=mixr[n-10];mixi[n]=mixi[n-10];}
    for(n=0;n<WIN;n++) hann[n]=(float)(.5-.5*cos(2*PI*n/(WIN-1)));
    for(n=0;n<FFT;n++) { unsigned x=n,y=0; for(j=0;j<FFT_LOG2;j++) {y=(y<<1)|(x&1); x>>=1;} reverse_bits[n]=y; }
    for(len=2;len<=FFT;len*=2) for(n=0;n<len/2;n++) {int ix=len/2-1+n;twiddle[ix].r=(float)cos(-2*PI*n/len);twiddle[ix].i=(float)sin(-2*PI*n/len);}
}
static void fft(void) {
    unsigned n,j,len;
    for(n=0;n<FFT;n++) if(reverse_bits[n]>n) { C a=spectrum[n]; spectrum[n]=spectrum[reverse_bits[n]]; spectrum[reverse_bits[n]]=a; }
    for(len=2;len<=FFT;len*=2) for(n=0;n<FFT;n+=len) {
      j=0;
#if defined(__ARM_NEON)
      for(;j+4<=len/2;j+=4) {
        float32x4x2_t a=vld2q_f32((float *)(spectrum+n+j)),b=vld2q_f32((float *)(spectrum+n+j+len/2));
        float32x4x2_t w=vld2q_f32((float *)(twiddle+len/2-1+j)),plus,minus;
        float32x4_t r=vsubq_f32(vmulq_f32(b.val[0],w.val[0]),vmulq_f32(b.val[1],w.val[1]));
        float32x4_t i=vaddq_f32(vmulq_f32(b.val[0],w.val[1]),vmulq_f32(b.val[1],w.val[0]));
        plus.val[0]=vaddq_f32(a.val[0],r);plus.val[1]=vaddq_f32(a.val[1],i);
        minus.val[0]=vsubq_f32(a.val[0],r);minus.val[1]=vsubq_f32(a.val[1],i);
        vst2q_f32((float *)(spectrum+n+j),plus);vst2q_f32((float *)(spectrum+n+j+len/2),minus);
      }
#endif
      for(;j<len/2;j++) {
        C a=spectrum[n+j],b=spectrum[n+j+len/2],w=twiddle[len/2-1+j];
        float r=b.r*w.r-b.i*w.i,i=b.r*w.i+b.i*w.r;
        spectrum[n+j].r=a.r+r; spectrum[n+j].i=a.i+i;
        spectrum[n+j+len/2].r=a.r-r; spectrum[n+j+len/2].i=a.i-i;
      }
    }
}
static unsigned byte_at(int pos) { unsigned b=0; int n; for(n=0;n<8;n++) b=(b<<1)|bits[pos+n]; return b; }
static void scan(Trial *trial,int nbits,int first,int invert) {
    int k,j,next=0; unsigned shift=0; memset(trial,0,sizeof(*trial));
    for(k=0;k<nbits;k++) {
        shift=((shift<<1)|bits[k])&0xffff;
        if(k<15||shift!=0xaaaa) continue;
        { int start=k-15,len,total; Frame f;
          if(start<next||start+24>nbits) continue;
          len=(int)byte_at(start+16); if(len<1||len>49) continue;
          total=(len+5)*8; if(start+total>nbits) continue;
          trial->complete++;
          for(j=0;j<len;j++) f.p[j]=(unsigned char)byte_at(start+24+j*8);
          f.crc=(byte_at(start+24+len*8)<<8)|byte_at(start+32+len*8);
          if(crc16(f.p,len)!=f.crc) { trial->rejects++; continue; }
          f.len=len; f.start=first+start*SPS; f.end=first+(start+total)*SPS;
          if(trial->count<MAXFRAMES) trial->f[trial->count++]=f;
          next=start+total;
        }
    }
    (void)invert;
}
static void hex(FILE *f,const unsigned char *p,int len) { int n; for(n=0;n<len;n++) fprintf(f,"%02x",p[n]); }
static void message_json(FILE *f,const Message *m) {
    fputs("{\"payload_hex\":\"",f); hex(f,m->p,m->len);
    fprintf(f,"\",\"payload_bytes\":%d,\"crc16\":%u,\"crc_valid\":true,\"carrier_offset_hz\":%.4f,\"first_symbol_sample\":%llu}",m->len,m->crc,m->cfo,(unsigned long long)m->sample);
}
static FILE *atomic_open(const char *suffix,char *path,char *temp) {
    if(snprintf(path,4096,"%s%s",prefix,suffix)>=4096||snprintf(temp,4096,"%s.tmp",path)>=4096) {output_failed=1;return NULL;}
    {FILE *f=fopen(temp,"wb"); if(!f) {perror(temp);output_failed=1;} return f;}
}
static void atomic_close(FILE *f,const char *path,const char *temp) {
    int bad=ferror(f); if(fclose(f)) bad=1;
    if(!bad) {
#ifdef _WIN32
        {int attempt;
         for(attempt=0;attempt<10;attempt++) {
            DWORD error;
            if(MoveFileExA(temp,path,MOVEFILE_REPLACE_EXISTING))break;
            error=GetLastError();
            if(error!=ERROR_SHARING_VIOLATION&&error!=ERROR_ACCESS_DENIED) {attempt=10;break;}
            Sleep(1);
         }
         if(attempt==10)bad=1;
        }
#else
        if(rename(temp,path)) bad=1;
#endif
    }
    if(bad) {fprintf(stderr,"stream_rx: cannot publish %s\n",path);output_failed=1;}
}
static void status_json(FILE *f,int eof) {
    fprintf(f,"{\"samples\":%llu,\"clips\":%llu,\"rms\":%.6f,\"frames\":%llu,\"rejects\":%llu,\"windows\":%llu,\"max_decode_ms\":%.3f,\"last_decode_ms\":%.3f,\"carrier_offset_hz\":%.4f,\"messages\":%d,\"sample_rate_hz\":2500000,\"decimated_rate_hz\":500000,\"hop_samples\":143360,\"eof\":%s,\"stopped\":%s,\"loss_measured\":false,\"input_error\":%s,\"uptime_ms\":%.3f,\"fft_ms\":%.3f,\"carrier_ms\":%.3f,\"matched_ms\":%.3f,\"recent_rms\":%.6f,\"recent_clips\":%llu",
        (unsigned long long)samples,(unsigned long long)clips,samples?sqrt((sumsq+(double)pending_energy)/samples):0,
        (unsigned long long)frames,(unsigned long long)rejects,(unsigned long long)windows,max_decode_ms,last_decode_ms,last_cfo,message_count,eof?"true":"false",stopping?"true":"false",input_error?"true":"false",now_ms()-started_ms,last_fft_ms,last_carrier_ms,last_matched_ms,recent_rms,(unsigned long long)recent_clips);
    lock_queue();
    fprintf(f,",\"acquired_samples\":%llu,\"queue_samples\":%llu,\"queue_capacity_samples\":%u,\"queue_high_water_samples\":%u,\"queue_backpressure_events\":%llu,\"read_ms_total\":%.3f,\"backpressure_ms_total\":%.3f",
        (unsigned long long)(acquired_bytes/4),(unsigned long long)(queue_bytes/4),
        QUEUE_BLOCKS*BLOCK_BYTES/4,queue_high*BLOCK_BYTES/4,(unsigned long long)backpressure_events,read_ms,backpressure_ms);
    unlock_queue();
    fprintf(f,",\"consumer_wait_ms_total\":%.3f,\"frontend_ms_total\":%.3f,\"decode_ms_total\":%.3f,\"fft_ms_total\":%.3f,\"carrier_ms_total\":%.3f,\"matched_ms_total\":%.3f,\"publish_ms_total\":%.3f,\"cpu_ms_total\":%.3f}",
        consumer_wait_ms,frontend_ms,decode_ms,fft_total_ms,carrier_total_ms,matched_total_ms,publish_ms,cpu_ms());
}
static void publish(int eof,int dirty) {
    char path[4096],temp[4096]; FILE *f; int n;double mark=now_ms();
    f=atomic_open(".status.json",path,temp); if(f) {status_json(f,eof); fputc('\n',f);atomic_close(f,path,temp);}
    if(dirty) {f=atomic_open(".messages.json",path,temp); if(f) {fputs("[",f);for(n=0;n<message_count;n++) {if(n) fputc(',',f);message_json(f,&messages[n]);} fputs("]\n",f);atomic_close(f,path,temp);}}
    if(stdio_mode) {fputs("{\"type\":\"status\",\"status\":",stdout);status_json(stdout,eof);fputs("}\n",stdout);fflush(stdout);}
    publish_ms+=now_ms()-mark;
}
static int accept_frame(const Frame *f,uint64_t base,double cfo) {
    int n; Message m;
    uint64_t end=(base+(unsigned)f->end)*5;
    /* Timing may select a neighboring raw-sample phase in another window. */
    if(frames&&end<=last_frame_end+SPS*5) return 0;
    last_frame_end=end; frames++;
    for(n=0;n<message_count;n++) if(messages[n].len==f->len&&!memcmp(messages[n].p,f->p,f->len)) return 0;
    if(message_count==HISTORY) {memmove(messages,messages+1,(HISTORY-1)*sizeof(Message));message_count--;}
    memcpy(m.p,f->p,f->len);m.len=f->len;m.crc=f->crc;m.cfo=cfo;
    /* Compensate the causal input FIR's 30 raw-sample group delay. */
    m.sample=(base+(unsigned)f->start)*5+4; if(m.sample>=30) m.sample-=30;
    messages[message_count++]=m;
    if(stdio_mode) {fputs("{\"type\":\"frame\",\"frame\":",stdout);message_json(stdout,&m);fputs("}\n",stdout);}
    return 1;
}
static void decode(int count,uint64_t base) {
    int n,k,t,inv,peak=0,limit=(int)(40000.0*FFT/CFO_FS),dirty=0; double bestpow=-1,delta=0,cfo,mark;float pr=0,pi=0;
    Trial best,trial; double started=now_ms(); memset(&best,0,sizeof(best));best.eye=-1;
    memset(spectrum,0,sizeof(spectrum));
    /* Square-law carrier tone survives a four-sample integrate-and-dump.
       Only the CFO branch is reduced; symbol decisions keep all 500k samples. */
    for(n=0;n<count;n++) {float a=window[n].r,b=window[n].i;float w=count==WIN?hann[n]:(float)(.5-.5*cos(2*PI*n/(count-1)));spectrum[n/CFO_DECIM].r+=(a*a-b*b)*w;spectrum[n/CFO_DECIM].i+=2*a*b*w;}
    fft();
    for(k=-limit;k<=limit;k++) {int ix=(k+FFT)%FFT; double p=(double)spectrum[ix].r*spectrum[ix].r+(double)spectrum[ix].i*spectrum[ix].i;if(p>bestpow) {bestpow=p;peak=ix;}}
    {double a[3],den;for(k=-1;k<=1;k++) {int ix=(peak+k+FFT)%FFT;a[k+1]=log(fmax((double)spectrum[ix].r*spectrum[ix].r+(double)spectrum[ix].i*spectrum[ix].i,1e-30));}den=a[0]-2*a[1]+a[2];if(den<0) delta=fmax(-.5,fmin(.5,.5*(a[0]-a[2])/den));}
    cfo=((peak>FFT/2?peak-FFT:peak)+delta)*CFO_FS/FFT/2;last_cfo=-250000+cfo;
    last_fft_ms=now_ms()-started;mark=now_ms();
    {float ar=(float)cos(-2*PI*cfo/500000),ai=(float)sin(-2*PI*cfo/500000),cr=1,ci=0;
      for(n=0;n<count;n++) {C a=window[n];float nr=cr*ar-ci*ai;work[n].r=a.r*cr-a.i*ci;work[n].i=a.r*ci+a.i*cr;pr+=work[n].r*work[n].r-work[n].i*work[n].i;pi+=2*work[n].r*work[n].i;ci=cr*ai+ci*ar;cr=nr;
        if((n&1023)==1023) {float gain=1/sqrtf(cr*cr+ci*ci);cr*=gain;ci*=gain;}}}
    {float cr=(float)cos(atan2(pi,pr)/2),ci=(float)sin(atan2(pi,pr)/2);
      for(n=0;n<count;n++) {float r=work[n].r,i=work[n].i;work[n].r=r*cr+i*ci;work[n].i=i*cr-r*ci;}}
    last_carrier_ms=now_ms()-mark;mark=now_ms();
    memset(matched,0,sizeof(matched));
    n=20;
#if defined(__ARM_NEON)
    for(;n+4<=count-20;n+=4) {
        float32x4x2_t v=vld2q_f32((float *)(work+n)),out;
        float32x4_t r=vmulq_n_f32(v.val[0],rrc[20]),i=vmulq_n_f32(v.val[1],rrc[20]);
        for(k=0;k<20;k++) {
            float32x4x2_t a=vld2q_f32((float *)(work+n+k-20)),b=vld2q_f32((float *)(work+n+20-k));
            r=vmlaq_n_f32(r,vaddq_f32(a.val[0],b.val[0]),rrc[k]);
            i=vmlaq_n_f32(i,vaddq_f32(a.val[1],b.val[1]),rrc[k]);
        }
        out.val[0]=r;out.val[1]=i;vst2q_f32((float *)(matched+n),out);
    }
#endif
    for(;n<count-20;n++) {
        float r=work[n].r*rrc[20],i=work[n].i*rrc[20];
        for(k=0;k<20;k++) {r+=(work[n+k-20].r+work[n+20-k].r)*rrc[k];i+=(work[n+k-20].i+work[n+20-k].i)*rrc[k];}
        matched[n].r=r;matched[n].i=i;
    }
    last_matched_ms=now_ms()-mark;
    for(t=0;t<SPS;t++) {int nbits=0;float eye=0,power=0;
      for(n=20+t;n<count-20;n+=SPS) {eye+=fabsf(matched[n].r);power+=matched[n].r*matched[n].r+matched[n].i*matched[n].i;bits[nbits++]=matched[n].r<0;}
      for(inv=0;inv<2;inv++) {if(inv)for(n=0;n<nbits;n++)bits[n]^=1;scan(&trial,nbits,20+t,inv);trial.eye=(float)(eye/sqrt(fmax(power*nbits,1e-30)));
        if(trial.count>best.count||(trial.count==best.count&&(trial.complete>best.complete||(trial.complete==best.complete&&trial.eye>best.eye)))) best=trial;}}
    for(n=0;n<best.count;n++) dirty|=accept_frame(&best.f[n],base,last_cfo);
    rejects+=best.rejects; windows++;last_decode_ms=now_ms()-started;if(last_decode_ms>max_decode_ms)max_decode_ms=last_decode_ms;
    decode_ms+=last_decode_ms;fft_total_ms+=last_fft_ms;carrier_total_ms+=last_carrier_ms;matched_total_ms+=last_matched_ms;
    publish(0,dirty);
}
static size_t prepare_input(const unsigned char *input,size_t count,int *fatal) {
    size_t n=0;uint64_t old_clips=clips,old_samples=samples;
#if defined(__ARM_NEON)
    uint64x2_t energy=vdupq_n_u64(0);uint32x4_t clip=vdupq_n_u32(0);
    for(;n+4<=count;n+=4) {
        int16x4x2_t raw=vld2_s16((const int16_t *)(input+n*4));
        int32x4_t ir=vmovl_s16(raw.val[0]),ii=vmovl_s16(raw.val[1]);
        uint32x4_t bad=vorrq_u32(vcgtq_u32(vaddq_u32(vreinterpretq_u32_s32(ir),vdupq_n_u32(2048)),vdupq_n_u32(4095)),vcgtq_u32(vaddq_u32(vreinterpretq_u32_s32(ii),vdupq_n_u32(2048)),vdupq_n_u32(4095)));
        uint64x2_t bad64=vreinterpretq_u64_u32(bad);
        float32x4_t a,b,cr,ci;float32x4x2_t z;
        if(vgetq_lane_u64(bad64,0)||vgetq_lane_u64(bad64,1))break;
        clip=vsubq_u32(clip,vorrq_u32(vceqq_s32(ir,vdupq_n_s32(-2048)),vceqq_s32(ir,vdupq_n_s32(2047))));
        clip=vsubq_u32(clip,vorrq_u32(vceqq_s32(ii,vdupq_n_s32(-2048)),vceqq_s32(ii,vdupq_n_s32(2047))));
        energy=vpadalq_u32(energy,vreinterpretq_u32_s32(vaddq_s32(vmull_s16(raw.val[0],raw.val[0]),vmull_s16(raw.val[1],raw.val[1]))));
        a=vcvtq_f32_s32(ir);b=vcvtq_f32_s32(ii);cr=vld1q_f32(mixr+mixer_phase);ci=vld1q_f32(mixi+mixer_phase);
        z.val[0]=vsubq_f32(vmulq_f32(a,cr),vmulq_f32(b,ci));z.val[1]=vaddq_f32(vmulq_f32(a,ci),vmulq_f32(b,cr));
        vst2q_f32((float *)(mixed_input+n),z);mixer_phase+=4;if(mixer_phase>=10)mixer_phase-=10;
    }
    pending_energy=vgetq_lane_u64(energy,0)+vgetq_lane_u64(energy,1);
    {uint32x2_t p=vadd_u32(vget_low_u32(clip),vget_high_u32(clip));p=vpadd_u32(p,p);clips+=vget_lane_u32(p,0);}
    samples+=n;
#endif
    for(;n<count;n++) {
        const unsigned char *p=input+4*n;
        int16_t ir=(int16_t)((unsigned)p[0]|(unsigned)p[1]<<8),ii=(int16_t)((unsigned)p[2]|(unsigned)p[3]<<8);
        float a=(float)ir,b=(float)ii;
        if(ir< -2048||ir>2047||ii< -2048||ii>2047) {fprintf(stderr,"stream_rx: input is not sign-extended S12 IQ at sample %llu\n",(unsigned long long)samples);*fatal=1;break;}
        samples++;clips+=(ir==-2048||ir==2047)+(ii==-2048||ii==2047);
        pending_energy+=(uint32_t)((int32_t)ir*ir+(int32_t)ii*ii);
        mixed_input[n].r=a*mixr[mixer_phase]-b*mixi[mixer_phase];mixed_input[n].i=a*mixi[mixer_phase]+b*mixr[mixer_phase];if(++mixer_phase==10)mixer_phase=0;
    }
    if(samples>old_samples) {recent_rms=sqrt((double)pending_energy/(samples-old_samples));recent_clips=clips-old_clips;}
    sumsq+=(double)pending_energy;pending_energy=0;
    return n;
}
int main(int argc,char **argv) {
    unsigned char input[65536+4];size_t pending=0,nread,n,valid;int pos=0,decim_phase=0,filled=0,fatal=0;uint64_t base=0;
    int a;
    if(argc<2||argc>4) {fprintf(stderr,"usage: stream_rx <output-prefix> [--stdio] [--live]\n");return 2;}
    prefix=argv[1];for(a=2;a<argc;a++) {
        if(!strcmp(argv[a],"--stdio"))stdio_mode=1;
        else if(!strcmp(argv[a],"--live"))live_mode=1;
        else return 2;
    }
#ifdef _WIN32
    InitializeCriticalSection(&queue_mutex);InitializeConditionVariable(&queue_cond);
    _setmode(_fileno(stdin),_O_BINARY);
    signal(SIGTERM,stop);signal(SIGINT,stop);
#else
    {struct sigaction sa;memset(&sa,0,sizeof(sa));sa.sa_handler=stop;sigaction(SIGTERM,&sa,NULL);sigaction(SIGINT,&sa,NULL);}
#endif
    started_ms=now_ms();init();publish(0,1);
#ifdef _WIN32
    reader_thread=CreateThread(NULL,0,read_input,NULL,0,NULL);
    if(!reader_thread)return 1;
#else
    if(pthread_create(&reader_thread,NULL,read_input,NULL))return 1;
#endif
    while(!stopping&&!output_failed) {
        double mark;
        nread=take_input(input+pending);if(!nread)break;nread+=pending;mark=now_ms();
        valid=prepare_input(input,nread/4,&fatal);
        for(n=0;n<valid;n++) {
            C z=mixed_input[n];
            history[pos]=history[pos+FIR]=z;if(++pos==FIR)pos=0;
            if(++decim_phase==5) {int j;float r=0,i=0;decim_phase=0;
#if defined(__ARM_NEON)
                float32x4_t vr=vdupq_n_f32(0),vi=vdupq_n_f32(0);float32x2_t pair;
                for(j=0;j+4<=FIR;j+=4) {float32x4x2_t h=vld2q_f32((float *)(history+pos+j));float32x4_t c=vld1q_f32(lowpass+j);vr=vmlaq_f32(vr,h.val[0],c);vi=vmlaq_f32(vi,h.val[1],c);}
                pair=vadd_f32(vget_low_f32(vr),vget_high_f32(vr));pair=vpadd_f32(pair,pair);r=vget_lane_f32(pair,0);
                pair=vadd_f32(vget_low_f32(vi),vget_high_f32(vi));pair=vpadd_f32(pair,pair);i=vget_lane_f32(pair,0);
                for(;j<FIR;j++) {r+=history[pos+j].r*lowpass[j];i+=history[pos+j].i*lowpass[j];}
#else
                {int lo=pos,hi=pos-1;
                if(hi<0)hi=FIR-1;
                /* Linear-phase symmetry halves the frontend multiplies. */
                for(j=0;j<FIR/2;j++) {
                    r+=(history[hi].r+history[lo].r)*lowpass[j];i+=(history[hi].i+history[lo].i)*lowpass[j];
                    if(--hi<0)hi=FIR-1;
                    if(++lo==FIR)lo=0;
                }
                r+=history[hi].r*lowpass[FIR/2];i+=history[hi].i*lowpass[FIR/2];
                }
#endif
                window[filled].r=r;window[filled++].i=i;decimated++;
                if(filled==WIN) {frontend_ms+=now_ms()-mark;decode(filled,base);mark=now_ms();memmove(window,window+HOP,KEEP*sizeof(C));filled=KEEP;base+=HOP;}
            }
        }
        frontend_ms+=now_ms()-mark;if(fatal)break;
        pending=nread-valid*4;memmove(input,input+valid*4,pending);
    }
    lock_queue();if(!stopping&&reader_error)fatal=1;unlock_queue();
    if(!stopping&&!fatal&&pending) {fprintf(stderr,"stream_rx: truncated IQ group (%u bytes)\n",(unsigned)pending);fatal=1;}
    input_error=fatal;
    if(!fatal&&filled>=SPS*48&&decimated>base+(windows?KEEP:0)) decode(filled,base);
    publish(!stopping&&!fatal&&!output_failed,0);
    /* All atomic output files are closed. A producer can still be blocked in
       fread holding stdin's FILE lock; libc exit would try to lock it again.
       Flush only our output streams, then terminate the whole process. The
       session owner separately stops the upstream IIO reader. */
    if(fflush(stdout))output_failed=1;
    if(fflush(stderr))output_failed=1;
    _Exit(fatal||output_failed?1:0);
}
