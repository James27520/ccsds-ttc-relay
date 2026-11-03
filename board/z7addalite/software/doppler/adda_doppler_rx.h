#ifndef ADDA_DOPPLER_RX_H
#define ADDA_DOPPLER_RX_H
#include "doppler.h"
#include "../demod/adda_receiver.h"
#define ADP_TC_LINK 1u
#define ADP_TC_RF_HZ 100500000.0
#define ADP_TC_IF_HZ 6750000.0
struct adp_trace {
    struct dp_output plan;
    double measured_cfo_hz, applied_correction_hz, applied_rate_hz_s;
    uint32_t capture_ms, sequence, clipped_samples;
    unsigned planned, crc_ok;
    int plan_result, observation_result;
};
/* This adapter is ONLY for ADC channel 0, 100.5 MHz -> +6.75 MHz alias.
 * capture_ms is the PS ARM-command timestamp, not decode completion. Current
 * hardware has no sample timestamp: uncertainty_ms bounds ARM-to-DONE polling.
 * No I/O, UDP, timers, RF enable, or telemetry format changes here. */
int adp_receive(struct dp_tracker *, const int16_t *, size_t,
                uint32_t capture_ms, uint32_t now_ms, uint32_t uncertainty_ms,
                uint32_t sequence, struct ap_frame_result *, adda_demod_stats *,
                struct adp_trace *);
#endif
