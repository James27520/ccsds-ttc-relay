#ifndef ADDA_CAPTURE_H
#define ADDA_CAPTURE_H
#include <stddef.h>
#include <stdint.h>
#include "capture_abi.h"

/* All addresses/constants come from the FPGA owner's single generated ABI.
 * The final platform must map these apertures Device/noncacheable and provide
 * real barriers. These callbacks allow complete offline fault/race testing. */
struct ac_io {
    void *context;
    int (*read32)(void *, uint32_t address, uint32_t *value);
    int (*write32)(void *, uint32_t address, uint32_t value);
    void (*barrier)(void *);
};
struct ac_policy {
    uint32_t build_id;
    uint8_t training_algorithm, a_test, b_test;
};
enum ac_state { AC_IDLE, AC_CONFIG, AC_WAIT_READY, AC_CAPTURING,
                AC_COPYING, AC_RELEASING, AC_READY, AC_ERROR };
enum ac_error { AC_OK, AC_EARG, AC_EBUS, AC_EIDENTITY, AC_EBUSY,
                AC_ECOMMAND, AC_ECONFIG, AC_ETRAINING, AC_ETIMEOUT,
                AC_ECAPTURE, AC_EMETADATA, AC_ERACE, AC_ESAMPLE, AC_ECANCEL };
struct ac_metadata {
    uint32_t epoch, select, count, written, format, adc_hz, output_hz, bytes;
    uint32_t config_epoch, flags, diag[4];
};
struct ac_capture {
    struct ac_io io;
    struct ac_policy policy;
    enum ac_state state;
    enum ac_error error;
    int16_t *samples;
    size_t capacity;
    uint32_t desired_mode, configuring_mode, select, epoch, config_epoch;
    uint32_t phase_started_ms, copied_words;
    unsigned valid;
    struct ac_metadata snapshot;
};
#define AC_TIMEOUT_MS 5000u
#define AC_COPY_WORDS_PER_POLL 1024u
void ac_init(struct ac_capture *, const struct ac_io *, const struct ac_policy *,
             int16_t *samples, size_t capacity);
/* Read-only check. A preliminary PS-only XSA does not implement this identity. */
int ac_probe(struct ac_capture *);
int ac_start(struct ac_capture *, uint32_t mode, unsigned channel, unsigned k,
              uint32_t now_ms);
void ac_poll(struct ac_capture *, uint32_t now_ms);
void ac_cancel(struct ac_capture *, uint32_t now_ms);
int ac_busy(const struct ac_capture *);
/* True only after validated BRAM copy AND acknowledged release to IDLE. */
int ac_normal_ready(const struct ac_capture *);
const char *ac_error_name(enum ac_error);
#endif
