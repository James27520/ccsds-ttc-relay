#include "adda_demod.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

#define PI 3.14159265358979323846
#define ADC_FS 31250000.0
#define IF_HZ 6750000.0
#define SEARCH_HZ 40000.0
#define SYMBOL_RATE 100000.0
#define DECIMATION 25u
#define LP_TAPS 511u
#define RRC_TAPS 101u
#define PHASES 16u

typedef struct { double re, im; } complex_pair;

static void fft(complex_pair *a, size_t n)
{
    size_t i, j, k, length;
    for (i=1, j=0; i<n; ++i) {
        size_t bit=n>>1;
        while (j & bit) { j^=bit; bit>>=1; }
        j^=bit;
        if (i<j) { complex_pair tmp=a[i]; a[i]=a[j]; a[j]=tmp; }
    }
    for (length=2; length<=n; length<<=1) {
        double wr=cos(-2*PI/length), wi=sin(-2*PI/length);
        for (i=0; i<n; i+=length) {
            double zr=1, zi=0;
            for (k=0; k<length/2; ++k) {
                complex_pair even=a[i+k], odd=a[i+k+length/2];
                double tr=odd.re*zr-odd.im*zi, ti=odd.re*zi+odd.im*zr;
                double next=zr*wr-zi*wi;
                a[i+k].re=even.re+tr; a[i+k].im=even.im+ti;
                a[i+k+length/2].re=even.re-tr;
                a[i+k+length/2].im=even.im-ti;
                zi=zr*wi+zi*wr; zr=next;
            }
        }
    }
}

static double power(complex_pair a) { return a.re*a.re+a.im*a.im; }

/* A real squared BPSK signal contains DC and +/-2fc. Evaluate only the
 * positive expected 2fc band; neither DC nor the data spectrum is a carrier. */
static complex_pair squared_line(const double *square, size_t n, double freq)
{
    complex_pair sum={0,0};
    double wr=cos(-2*PI*freq/ADC_FS), wi=sin(-2*PI*freq/ADC_FS);
    double zr=1,zi=0;
    size_t i;
    for (i=0;i<n;++i) {
        double next=zr*wr-zi*wi;
        sum.re+=square[i]*zr; sum.im+=square[i]*zi;
        zi=zr*wi+zi*wr; zr=next;
    }
    return sum;
}

static double sinc(double x)
{
    return fabs(x)<1e-12 ? 1.0 : sin(PI*x)/(PI*x);
}

static void make_filters(double *lowpass, double *rrc)
{
    unsigned i;
    double sum=0, energy=0;
    const double beta=.35, sps=ADC_FS/DECIMATION/SYMBOL_RATE;
    for (i=0;i<LP_TAPS;++i) {
        double t=(double)i-(LP_TAPS-1)/2.0;
        double cutoff=200000.0/ADC_FS;
        lowpass[i]=2*cutoff*sinc(2*cutoff*t)*
                   (.54-.46*cos(2*PI*i/(LP_TAPS-1)));
        sum+=lowpass[i];
    }
    for(i=0;i<LP_TAPS;++i) lowpass[i]/=sum;
    for(i=0;i<RRC_TAPS;++i) {
        double t=((double)i-(RRC_TAPS-1)/2.0)/sps;
        double v;
        if(fabs(t)<1e-10) v=1-beta+4*beta/PI;
        else if(fabs(fabs(t)-1/(4*beta))<1e-10)
            v=beta/sqrt(2.0)*((1+2/PI)*sin(PI/(4*beta))+
                             (1-2/PI)*cos(PI/(4*beta)));
        else v=(sin(PI*t*(1-beta))+4*beta*t*cos(PI*t*(1+beta)))/
               (PI*t*(1-16*beta*beta*t*t));
        rrc[i]=v; energy+=v*v;
    }
    for(i=0;i<RRC_TAPS;++i) rrc[i]/=sqrt(energy);
}

int adda_demod(const int16_t *samples, size_t count,
               adda_bits_callback callback, void *context,
               adda_demod_stats *stats)
{
    size_t nfft=1, i, k, peak, lo, hi, nbase, nmatched;
    double mean=0, variance=0, square_mean=0, best=-1;
    double *square=NULL, *mixed=NULL, *base=NULL, *matched=NULL;
    complex_pair *spectrum=NULL;
    uint8_t *bits=NULL;
    double lowpass[LP_TAPS],rrc[RRC_TAPS],freq,phase;
    int result=-2;
    unsigned trial;
    if(!samples || !callback || !stats || count<65536 || count>262144)
        return -1;
    memset(stats,0,sizeof(*stats));
    while(nfft<count) nfft<<=1;
    nbase=(count-LP_TAPS)/DECIMATION+1;
    nmatched=nbase-RRC_TAPS+1;
    square=calloc(count,sizeof(*square));
    mixed=calloc(count,sizeof(*mixed));
    spectrum=calloc(nfft,sizeof(*spectrum));
    base=calloc(nbase,sizeof(*base));
    matched=calloc(nmatched,sizeof(*matched));
    bits=calloc(nmatched,sizeof(*bits));
    if(!square || !mixed || !spectrum || !base || !matched || !bits) goto done;
    for(i=0;i<count;++i) mean+=samples[i];
    mean/=count;
    for(i=0;i<count;++i) {
        double x=samples[i]-mean;
        variance+=x*x;
        square[i]=x*x;
    }
    square_mean=variance/count;
    stats->input_rms=sqrt(square_mean);
    if(stats->input_rms<1e-9) {result=0;goto done;}
    for(i=0;i<count;++i) {
        square[i]=(square[i]-square_mean)*(.5-.5*cos(2*PI*i/(count-1)));
        spectrum[i].re=square[i];
    }
    fft(spectrum,nfft);
    lo=(size_t)ceil(2*(IF_HZ-SEARCH_HZ)*nfft/ADC_FS);
    hi=(size_t)(2*(IF_HZ+SEARCH_HZ)*nfft/ADC_FS);
    peak=lo;
    for(k=lo;k<=hi;++k) {
        double p=power(spectrum[k]);
        if(p>best) { best=p; peak=k; }
    }
    {
        double a=power(spectrum[peak-1]), b=power(spectrum[peak]);
        double c=power(spectrum[peak+1]), denom=a-2*b+c;
        double offset=fabs(denom)>1e-30 ? .5*(a-c)/denom : 0;
        double left,right,x1,x2,p1,p2;
        unsigned iteration;
        if(offset<-.5) offset=-.5;
        if(offset>.5) offset=.5;
        freq=(peak+offset)*ADC_FS/nfft;
        /* Refine the parabolic FFT estimate within its main lobe, avoiding
         * systematic bin interpolation bias on short captures. */
        left=freq-ADC_FS/nfft*.7; right=freq+ADC_FS/nfft*.7;
        if(left<2*(IF_HZ-SEARCH_HZ)) left=2*(IF_HZ-SEARCH_HZ);
        if(right>2*(IF_HZ+SEARCH_HZ)) right=2*(IF_HZ+SEARCH_HZ);
        x1=right-(right-left)*.61803398875;
        x2=left+(right-left)*.61803398875;
        p1=power(squared_line(square,count,x1));
        p2=power(squared_line(square,count,x2));
        for(iteration=0;iteration<16;++iteration) {
            if(p1>p2) {
                right=x2; x2=x1; p2=p1;
                x1=right-(right-left)*.61803398875;
                p1=power(squared_line(square,count,x1));
            } else {
                left=x1; x1=x2; p1=p2;
                x2=left+(right-left)*.61803398875;
                p2=power(squared_line(square,count,x2));
            }
        }
        freq=(left+right)/2;
    }
    {
        complex_pair line=squared_line(square,count,freq);
        phase=.5*atan2(line.im,line.re);
    }
    freq*=.5;
    stats->carrier_hz=freq; stats->carrier_phase=phase;
    {
        double zr=cos(phase),zi=sin(phase);
        double wr=cos(2*PI*freq/ADC_FS),wi=sin(2*PI*freq/ADC_FS);
        for(i=0;i<count;++i) {
            double next=zr*wr-zi*wi;
            mixed[i]=2*(samples[i]-mean)*zr;
            zi=zr*wi+zi*wr; zr=next;
        }
    }
    make_filters(lowpass,rrc);
    for(i=0;i<nbase;++i)
        for(k=0;k<LP_TAPS;++k) base[i]+=mixed[i*DECIMATION+k]*lowpass[k];
    for(i=0;i<nmatched;++i)
        for(k=0;k<RRC_TAPS;++k) matched[i]+=base[i+k]*rrc[k];
    result=0;
    for(trial=0;trial<PHASES;++trial) {
        const double sps=ADC_FS/DECIMATION/SYMBOL_RATE;
        double position=sps*trial/PHASES;
        size_t nbits=0;
        while(position+1<nmatched) {
            size_t index=(size_t)position;
            double frac=position-index;
            double sample=matched[index]*(1-frac)+matched[index+1]*frac;
            bits[nbits++]=(uint8_t)(sample<0);
            position+=sps;
        }
        stats->symbol_candidates=nbits;
        stats->timing_trials=trial+1;
        if(callback(bits,nbits,trial,context)) {result=1;break;}
    }
done:
    free(square);free(mixed);free(spectrum);free(base);free(matched);free(bits);
    return result;
}
