#ifndef ADDA_PATTERN_CHECK_H
#define ADDA_PATTERN_CHECK_H
#include <stdint.h>
#include <stddef.h>
struct apc_result {
    uint32_t samples,transitions,mismatches,zero_states,invalid_samples,toggle_mask;
    uint32_t first_raw,last_raw;
};
/* Internal TRAINING captures only. A is PN9 with 15 bits per ADC sample and
 * decimation four => 60 steps; B checker becomes one fixed raw14 value.
 * The XOR is only for checking test patterns; input buffer is never changed. */
int apc_check(const int16_t *samples,size_t count,unsigned channel,struct apc_result *);
#endif
