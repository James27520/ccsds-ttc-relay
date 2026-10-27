#include "adda_pattern_check.h"
#include <string.h>
static uint16_t next_pn(uint16_t previous)
{
    uint32_t state=previous&0x1ffu,word=0u;unsigned i;
    for(i=0;i<60u;++i) {
        uint32_t bit=((state>>8)^(state>>4))&1u;
        state=((state<<1)|bit)&0x1ffu;word=((word<<1)|bit)&0x3fffu;
    }
    return (uint16_t)word;
}
int apc_check(const int16_t *samples,size_t count,unsigned channel,struct apc_result *out)
{
    size_t i;uint16_t previous=0u,raw=0u,normalized=0u;
    if(!samples || !out || count<512u || count>UINT32_MAX || channel>1u)return -1;
    memset(out,0,sizeof(*out));out->samples=(uint32_t)count;out->transitions=(uint32_t)count-1u;
    for(i=0;i<count;++i) {
        if(samples[i]<-8192 || samples[i]>8191)++out->invalid_samples;
        raw=(uint16_t)samples[i]&0x3fffu;
        if(!i)out->first_raw=raw;
        if(channel==0u) {
            normalized=raw^0x3fffu;
            if(!(normalized&0x1ffu))++out->zero_states;
            if(i) {if(next_pn(previous)!=normalized)++out->mismatches;out->toggle_mask|=previous^normalized;}
            previous=normalized;
        } else if((raw!=0x1555u && raw!=0x2aaau) || raw!=out->first_raw)++out->mismatches;
    }
    out->last_raw=raw;
    return out->mismatches==0u && out->zero_states==0u && out->invalid_samples==0u &&
      (channel==1u || out->toggle_mask==0x3fffu)?1:0;
}
