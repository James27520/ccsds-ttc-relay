#include "adda_receiver.h"

static int accept_frame(const uint8_t *bits, size_t count,
                        unsigned phase, void *context)
{
    (void)phase;
    return ap_find_frame(bits,count,0,(struct ap_frame_result *)context)==AP_OK;
}

int adda_receive(const int16_t *samples, size_t count,
                 struct ap_frame_result *frame, adda_demod_stats *stats)
{
    if(!frame) return -1;
    return adda_demod(samples,count,accept_frame,frame,stats);
}
