#include "relay_doppler.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static uint32_t iq[RD_SAMPLES];
static void wave(double f, unsigned zero)
{
    unsigned k;
    for(k=0;k<RD_SAMPLES;++k) {
        double p=6.283185307179586*f*k/RD_FS, sign=(k/307)%2?-1:1;
        int i=zero?0:(int)lround(300*sign*cos(p));
        int q=zero?0:(int)lround(300*sign*sin(p));
        iq[k]=((uint32_t)i&4095u)|(((uint32_t)q&4095u)<<16);
    }
}
int main(int argc,char **argv)
{
    unsigned ch; struct rd_channel s[2]; struct rd_measurement m;
    struct dp_output in,out; uint32_t word;
    const double incoming[2]={12000,-15000}, outgoing[2]={-8000,6000};
    if(argc==2 && !strcmp(argv[1],"--rtl-output")) {
        FILE *f=fopen("mixed_iq.txt","r");unsigned n;uint32_t buffers[2][4000];assert(f);
        for(n=0;n<4000;++n)assert(fscanf(f,"%x %x",&buffers[0][n],&buffers[1][n])==2);
        fclose(f);
        for(ch=0;ch<2;++ch){
            assert(!rd_measure(buffers[ch],4000,RD_FS,500000,&m) && m.valid);
            printf("RTL ch=%u residual_after_downlink=%.3f Hz\n",ch+1,m.cfo_hz+outgoing[ch]);
            assert(fabs(m.cfo_hz+outgoing[ch])<15);
        }
        puts("MIXER_PASS: C estimator/NCO words drive existing dual-channel RTL, both correction signs");return 0;
    }
    for(ch=0;ch<2;++ch) {
        double fi=1989500000.,fo=2179500000.,bias=ch?-250:300,actual=incoming[ch]+bias;
        rd_init(&s[ch],ch);
        assert(rd_step(&s[ch],0,1,&word,&in,&out)==0 && word==0);
        assert(!rd_configure(&s[ch],100,1000,fi,fo,fi-500000,fo-500000,
            -incoming[ch]*299792458./fi,0,-outgoing[ch]*299792458./fo,0,0,0));
        assert(rd_step(&s[ch],110,1,&word,&in,&out)==1);
        assert(fabs(rd_hz(word,RD_FS)-incoming[ch]-outgoing[ch])<.01);
        wave(500000+actual,0);
        assert(!rd_measure(iq,RD_SAMPLES,RD_FS,500000,&m) && m.valid);
        assert(fabs(m.cfo_hz-actual)<5);
        assert(!rd_observe(&s[ch],&m,110,111,1));
        assert(rd_observe(&s[ch],&m,110,111,1)==DP_ORDER);
        assert(rd_step(&s[ch],150,1,&word,&in,&out)==1 && in.state==DP_HYBRID);
        printf("ch=%u input_cfo=%.3f measured=%.3f downlink_cfo=%.3f correction=%.3f residual=%.3f\n",
            ch+1,actual,m.cfo_hz,outgoing[ch],-rd_hz(word,RD_FS),actual+outgoing[ch]-rd_hz(word,RD_FS));
        assert(fabs(actual+outgoing[ch]-rd_hz(word,RD_FS))<5);
        {
            char filename[30]; FILE *f;unsigned k;
            snprintf(filename,sizeof(filename),"business_ch%u.hex",ch); f=fopen(filename,"w");assert(f);
            fprintf(f,"%08x\n",word);for(k=0;k<RD_SAMPLES;++k)fprintf(f,"%08x\n",iq[k]);fclose(f);
        }
        wave(0,1); assert(!rd_measure(iq,RD_SAMPLES,RD_FS,500000,&m) && !m.valid);
        assert(rd_observe(&s[ch],&m,160,161,2)==DP_QUALITY);
    }
    assert(rd_step(&s[0],1100,1,&word,&in,&out)==-1 && word==0 && !s[0].enabled);
    assert(rd_step(&s[1],200,0,&word,&in,&out)==-1 && word==0 && !s[1].enabled);
    assert(rd_step(&s[1],210,1,&word,&in,&out)==0 && word==0); // no resurrection
    assert(rd_configure(&s[0],0,1000,1989500000.,2179500000.,1989000000.,2178000000.,0,0,0,0,0,0)<0);
    // Retain nonzero existing DDC/DUC and restore it exactly at expiry.
    word=rd_word(-1000,RD_FS);
    assert(!rd_configure(&s[0],0,100,1989500000.,2179500000.,1989000000.,2179000000.,0,0,0,0,word,word));
    assert(rd_step(&s[0],50,1,&word,&in,&out)==1 && word==s[0].base_ddc);
    assert(rd_step(&s[0],100,1,&word,&in,&out)==-1 && word==s[0].base_ddc);
    // Once configured, advancing only the onboard clock updates the NCO.
    assert(!rd_configure(&s[0],0,1000,1989500000.,2179500000.,1989000000.,2179000000.,
        0,-100*299792458./1989500000.,0,40*299792458./2179500000.,0,0));
    assert(rd_step(&s[0],100,1,&word,&in,&out)==1 && fabs(rd_hz(word,RD_FS)-6)<.01);
    assert(rd_step(&s[0],500,1,&word,&in,&out)==1 && fabs(rd_hz(word,RD_FS)-30)<.01);
    puts("BUSINESS_DOPPLER_PASS: two directions, signed correction, invalid observation, expiry, lease, baseline");
    return 0;
}
