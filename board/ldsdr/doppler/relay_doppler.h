#ifndef RELAY_DOPPLER_H
#define RELAY_DOPPLER_H
#include "doppler.h"
#include <stddef.h>

#define RD_SAMPLES 4096u
#define RD_LAG 32u
#define RD_FS 30720000u
struct rd_measurement { double cfo_hz, coherence, rms; unsigned clipped, valid; };
struct rd_channel {
    struct dp_tracker incoming, outgoing;
    double nominal_if_hz;
    uint32_t base_ddc, base_duc, last_ddc;
    unsigned enabled;
};
/* Samples: signed 12-bit I in [11:0], signed Q in [27:16]. Raw, pre-DDC.
 * BPSK square-law lag correlation; signal quality, not packet CRC, gates it. */
int rd_measure(const uint32_t *, size_t, double fs, double nominal_if,
               struct rd_measurement *);
uint32_t rd_word(double hz, double fs);
double rd_hz(uint32_t word, double fs);
void rd_init(struct rd_channel *, unsigned channel);
int rd_configure(struct rd_channel *, uint32_t now, uint32_t ttl,
    double input_rf, double output_rf, double rx_lo, double tx_lo,
    double in_velocity, double in_acceleration, double out_velocity,
    double out_acceleration, uint32_t base_ddc, uint32_t base_duc);
int rd_observe(struct rd_channel *, const struct rd_measurement *,
               uint32_t capture_ms, uint32_t now, uint32_t seq);
/* Returns the absolute DDC word, preserving the existing frequency plan.
 * Invalid/expired model disables compensation and restores baseline. */
int rd_step(struct rd_channel *, uint32_t now, unsigned leased,
            uint32_t *word, struct dp_output *incoming, struct dp_output *outgoing);
#endif
