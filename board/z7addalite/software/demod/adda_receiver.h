#ifndef ADDA_RECEIVER_H
#define ADDA_RECEIVER_H
#include "adda_demod.h"
#include "../protocol/adda_protocol.h"
/* First complete valid frame in a capture. Does not execute the command. */
int adda_receive(const int16_t *samples, size_t count,
                 struct ap_frame_result *frame, adda_demod_stats *stats);
int adda_receive_planned(const int16_t *samples, size_t count,
                         struct ap_frame_result *frame, adda_demod_stats *stats,
                         const adda_demod_plan *plan);
#endif
