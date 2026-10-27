#ifndef ADDA_DEMOD_H
#define ADDA_DEMOD_H
#include <stddef.h>
#include <stdint.h>

/* Offline/PS-independent front end. Samples are signed, equally spaced ADC
 * values at 31.25 MSPS, after the PL acquisition format has been unpacked:
 * one channel, raw 14-bit two's-complement sign-extended to int16_t, no shift.
 * Input is 31.25M samples/s: current ADC 125M, one out of four (no boxcar).
 * The caller must check capture metadata; no ADC register layout is assumed. */
typedef struct {
    double carrier_hz;
    double carrier_phase;
    double input_rms;
    size_t symbol_candidates;
    unsigned timing_trials;
} adda_demod_stats;

/* Return nonzero only after the caller validates ASM, decoding, CRC and range.
 * Polarity ambiguity is intentionally left to the frame decoder. */
typedef int (*adda_bits_callback)(const uint8_t *bits, size_t count,
                                  unsigned timing_phase, void *context);

/* Fixed V2 PHY: Fs=31.25M, expected IF=6.75M +/-40k, Rs=100k, beta=.35.
 * Returns 1 if callback accepts a candidate, 0 if none, negative on error.
 * Captures of 65536..262144 samples are supported; 131072 is the baseline.
 * 65536 is not a guaranteed full-frame capture at arbitrary start phase.
 * No I/O, network, device control, or assertions of RF provenance. */
int adda_demod(const int16_t *samples, size_t count,
               adda_bits_callback callback, void *context,
               adda_demod_stats *stats);
#endif
