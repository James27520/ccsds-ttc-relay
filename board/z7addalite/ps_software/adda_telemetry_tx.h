#ifndef ADDA_TELEMETRY_TX_H
#define ADDA_TELEMETRY_TX_H
#include "adda_ps_core.h"

/* Custom experimental telemetry, NOT a complete CCSDS frame. All multibyte
 * fields are big endian. Sequence and uptime restart at boot; no boot nonce.
 * No function in the portable serializer accesses hardware. */
#define ATM_PAYLOAD_BYTES 96u
#define ATM_FRAME_BYTES 101u
#define ATM_BURST_BYTES 420u
#define ATM_BUFFER_BYTES 512u
#define ATM_REPEAT_COUNT 4u
#ifndef ADDA_TM_TX_ENABLED
#define ADDA_TM_TX_ENABLED 0
#endif
int atm_pack(const struct aps_state *state,uint32_t sequence,uint32_t uptime_ms,
             uint8_t *output,size_t capacity);
int atm_frame(const uint8_t *payload,size_t length,uint8_t *output,size_t capacity);
/* 64 alternating training bits | four identical frames | 64 trailing bits.
 * At 100 ksym/s this finite burst lasts 33.6 ms. Bytes transmit MSB first.
 * Repeated records describe one snapshot, not four independent events. */
int atm_burst(const struct aps_state *state,uint32_t sequence,uint32_t uptime_ms,
              uint8_t *output,size_t capacity);
uint32_t atm_word(const uint8_t *bytes,size_t length,size_t word_index);
#define ATM_TX_BASE UINT32_C(0x43c01000)
#define ATM_TX_MAGIC UINT32_C(0x544d5431)
#define ATM_TX_DISABLED (-20)
struct atm_io {
    void *context;
    int (*read32)(void *,uint32_t,uint32_t *);
    int (*write32)(void *,uint32_t,uint32_t);
    void (*barrier)(void *);
};
struct atm_tx { struct atm_io io; uint32_t sequence,started_ms; unsigned pending,stopping; };
/* Default builds return DISABLED without invoking ANY MMIO callback. With
 * explicit opt-in, init issues STOP on the identified extension to prevent a
 * PS application restart from leaving an old transmission running. */
int atm_tx_init(struct atm_tx *tx,const struct atm_io *io);
int atm_tx_status(struct atm_tx *tx,uint32_t *status,uint32_t *diagnostic);
int atm_tx_configuration(struct atm_tx *tx,uint32_t *flags,uint32_t *diagnostic);
int atm_tx_send(struct atm_tx *tx,const struct aps_state *state,uint32_t now_ms);
/* Submit already serialized immutable bytes; does NOT allocate a sequence.
 * Autonomous service allocates once on its first successful submission. */
int atm_tx_send_burst(struct atm_tx *tx,const uint8_t *burst,size_t length,uint32_t now_ms);
int atm_tx_stop(struct atm_tx *tx);
/* Explicit recovery of a stopped/faulted buffer; never clears while owned. */
int atm_tx_clear(struct atm_tx *tx);
/* Network state is informational: explicit telemetry may report a network
 * failure. The network-off CLI independently calls STOP. PL's finite length
 * bounds transmission even if capture/decoding delays this PS poll. */
int atm_tx_poll(struct atm_tx *tx,unsigned network_ready,uint32_t now_ms);
#endif
