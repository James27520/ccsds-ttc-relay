#ifndef ADDA_PROTOCOL_H
#define ADDA_PROTOCOL_H

/* Portable C99, hard-decision digital frame layer ONLY. No ADC demodulation,
 * socket, board access, clock, heap, or mutable globals. Bits are bytes 0/1. */
#include <stddef.h>
#include <stdint.h>

#define AP_BODY_BYTES 8u
#define AP_DATA_BITS 64u
#define AP_CODE_BITS 128u
#define AP_FRAME_BITS 160u
#define AP_RF_BYTES 26u
#define AP_ACK_MAX_BYTES 96u

enum ap_status {
    AP_OK = 0, AP_DUPLICATE = 1, AP_PENDING = 2,
    AP_EARG = -1, AP_ELENGTH = -2, AP_EBIT = -3, AP_ECRC = -4,
    AP_EVERSION = -5, AP_ERANGE = -6, AP_ENOFRAME = -7,
    AP_ETRUNCATED = -8, AP_EACK = -9, AP_ESTALE = -10,
    AP_ECONFLICT = -11, AP_EBUSY = -12, AP_EREMOTE = -13,
    AP_EMISMATCH = -14
};

struct ap_command {
    uint8_t version;
    uint16_t rx_mhz;
    uint16_t tx_mhz;
    uint8_t seq;
};

struct ap_frame_result {
    struct ap_command command;
    uint8_t body[AP_BODY_BYTES];
    size_t bit_offset;
    unsigned asm_errors;
    unsigned inverted;
    unsigned path_metric;
    unsigned end_state;
};

uint16_t ap_crc16(const uint8_t *data, size_t length);
int ap_body_build(const struct ap_command *command, uint8_t body[AP_BODY_BYTES]);
int ap_body_parse(const uint8_t *body, size_t length, struct ap_command *command);
/* Reset seed 0xff for each call. In-place operation is allowed. */
int ap_randomize_bits(const uint8_t *input, uint8_t *output, size_t length);
int ap_conv_encode64(const uint8_t input[AP_DATA_BITS], uint8_t output[AP_CODE_BITS]);
/* Initial state 0, no tail bits, choose minimum-metric final state. */
int ap_viterbi64(const uint8_t input[AP_CODE_BITS], uint8_t output[AP_DATA_BITS],
                 unsigned *metric, unsigned *end_state);
int ap_frame_encode(const struct ap_command *command, uint8_t output[AP_FRAME_BITS]);
/* Search bitwise from start_bit, try normal/inverted ASM with <=2 errors.
 * Keep searching after invalid/CRC-failed candidates. Return first fully valid
 * frame. On failure result is untouched. Advance next start by offset+160 for
 * nonoverlapping frame iteration. A truncated candidate yields AP_ETRUNCATED
 * only if no complete valid candidate is found. No waveform timing/phase work. */
int ap_find_frame(const uint8_t *bits, size_t bit_count, size_t start_bit,
                   struct ap_frame_result *result);

struct ap_ack { int32_t rc; uint16_t seq; uint64_t rx_hz; uint64_t tx_hz; };
/* Existing LDSDR UDP RF_SET wire format, not the UART CLI. gain/attenuation
 * must be supplied explicitly. 70..6000 MHz is a wire limit, not RF assurance. */
int ap_rf_packet(const struct ap_command *command, uint16_t transaction_seq,
                   uint8_t rx_gain_db, uint8_t tx_att_db, uint8_t output[AP_RF_BYTES]);
/* Parse exactly "rc=%d seq=%u rx_hz=%llu tx_hz=%llu\n" (also CRLF).
 * Length is the datagram byte count; no NUL terminator is expected or required. */
int ap_ack_parse(const uint8_t *text, size_t length, struct ap_ack *ack);

/* One outstanding transaction. State is caller-owned. Network layer MUST
 * validate the expected peer address/port BEFORE accepting an ACK. No clock or
 * retry loop is hidden here; bounded retry/session/replay policy is external.
 * Air seq8 equality detects duplicates/conflicts only. Different air seq8
 * values impose no ordering or half-window rule, matching the V2 contract.
 * Applied command changes only on a successful matching ACK. */
struct ap_transaction {
    unsigned pending;
    unsigned applied_valid;
    uint16_t next_transaction_seq;
    uint16_t pending_transaction_seq;
    struct ap_command pending_command;
    struct ap_command applied_command;
    uint8_t pending_gain;
    uint8_t pending_attenuation;
    uint8_t applied_gain;
    uint8_t applied_attenuation;
    uint8_t packet[AP_RF_BYTES];
};
void ap_transaction_init(struct ap_transaction *state, uint16_t first_transaction_seq);
int ap_transaction_begin(struct ap_transaction *state, const struct ap_command *command,
                           uint8_t rx_gain_db, uint8_t tx_att_db);
/* Every non-success response leaves pending/applied state untouched. The caller
 * decides retry versus abort. tolerance_hz <=10000 matches legacy apply check. */
int ap_transaction_ack(struct ap_transaction *state, const struct ap_ack *ack,
                        uint32_t tolerance_hz);
/* Ends an unsuccessful attempt without marking applied. Next begin uses a new
 * UDP sequence. Does not cancel a datagram already in flight on the server. */
void ap_transaction_abort(struct ap_transaction *state);

#endif
