#ifndef ADDA_PS_CORE_H
#define ADDA_PS_CORE_H
#include <stddef.h>
#include <stdint.h>
#include "adda_protocol.h"
#include "adda_receiver.h"

/* Host-testable control core. No hardware addresses, BSP headers or sockets.
 * The future ADDA-specific platform adapter provides UART and UDP callbacks. */
enum aps_origin { APS_ADC_NORMAL=1, APS_ADC_TEST=2, APS_SYNTHETIC=3, APS_UART_NETTEST=4 };
#define APS_RELAY_IPV4 UINT32_C(0xa9fe090a) /* host numeric A.B.C.D = 169.254.9.10 */
#define APS_RELAY_PORT 5005u
#define APS_RETRY_MS 250u
#define APS_MAX_SENDS 3u
#define APS_TM1_MAX_BYTES 1024u /* includes CRLF and terminating NUL */
/* Records survive PC reconnects, not aps_init/reboot. Each stage owns its
 * origin/command, so a newer local decode cannot relabel an older ACK. */
struct aps_command_record {
    unsigned valid;
    uint32_t event;
    enum aps_origin origin;
    struct ap_command command;
};
struct aps_send_record {
    struct aps_command_record record;
    uint16_t transaction_seq;
    unsigned count; /* total attempts for this transaction, not retransmits */
    int rc; /* transport acceptance only; never remote execution evidence */
};
struct aps_ack_record {
    struct aps_command_record record;
    struct ap_ack reply; /* matched remote ACK; binary failures also retained */
    struct ap_relay_status status; /* binary ACK snapshot only */
};
struct aps_io {
    void *context;
    void (*log)(void *context, const char *text);
    /* Return 0 only when the transport accepted the packet for sending.
     * This callback must never be called from a selftest/synthetic source. */
    int (*udp_send)(void *context, uint32_t peer_ipv4, uint16_t port,
                    const uint8_t *bytes, size_t length);
};
struct aps_state {
    struct aps_io io;
    struct ap_transaction transaction;
    unsigned network_ready;
    unsigned armed;
    uint8_t rx_gain_db;
    uint8_t tx_attenuation_db;
    enum aps_origin pending_origin;
    unsigned sends;
    uint32_t last_send_ms;
    unsigned decoded_frames;
    unsigned applied_commands;
    unsigned failed_transactions;
    uint32_t telemetry_events; /* decoded, send attempt, matched retained ACK */
    struct aps_command_record last_decoded;
    struct aps_send_record last_send;
    struct aps_ack_record last_ack;
};
/* Stable TM1 wire contract: fixed field order, decimal integer values (origin
 * uses enum aps_origin; 0 means unknown), then " crc16=HHHH\r\n". CRC is
 * CRC-16/CCITT-FALSE over ASCII from 'T' through the final spi_valid value;
 * excludes the space before crc16, CRC field, CRLF and NUL. It detects line
 * corruption/truncation, not authenticity or truth of remote hardware state.
 * uptime_ms is the caller's platform clock modulo 2^32 (49.7-day wrap); event
 * IDs also wrap modulo 2^32. valid, never event!=0, determines presence.
 * spi_valid is always 0: this core has no independent LDSDR SPI readback.
 * A new-operation negative ACK appears as an entirely zeroed invalid ACK in
 * TM1 to preserve its successful-ACK meaning; the original failure remains
 * in state, REMOTE_ACK and ATM2. Formatting never changes the stored record.
 * Read-only, serialized core caller required (same as all existing core APIs).
 * Returns line length excluding NUL, or AP_EARG/AP_ELENGTH; an undersized
 * nonempty buffer is cleared rather than returning a partial valid-looking TM1.
 * Future field/order/meaning changes require a new TM version. */
int aps_telemetry_format(const struct aps_state *state, uint32_t uptime_ms,
                         char *output, size_t capacity);
void aps_init(struct aps_state *state, const struct aps_io *io);
void aps_set_network_ready(struct aps_state *state, unsigned ready);
/* Line excludes newline, <=127 characters. status/telemetry/help/selftest are read-only.
 * nettest RX_MHz TX_MHz SEQ GAIN ATT is an explicit known-command test.
 * remotenettest enable/stop/status RX_MHz TX_MHz SEQ LEASE_MS is explicitly
 * UART_NETTEST, requires disarmed/network ready. Platform/controller must also
 * enforce inactive service, automatic off, and no capture in progress. Only
 * this diagnostic entrance overrides enable's fixed 300000 ms ADC lease.
 * arm on/off controls automatic ADC-only forwarding, off at startup. */
int aps_command_line(struct aps_state *state, const char *line, uint32_t now_ms);
int aps_selftest(struct aps_state *state);
/* This API revalidates the 8-byte body. ADC origin may only be assigned by a
 * platform adapter which validated the frozen capture's ABI/count/epoch,
 * overflow, normal-mode readback, sample format and 31.25MSPS metadata.
 * Decoding does not create provenance; synthetic/test captures stay test. */
int aps_accept_decoded(struct aps_state *state, const struct ap_frame_result *frame,
                        enum aps_origin origin, uint32_t now_ms);
/* No MMIO: samples already belong to a validated, frozen local snapshot. */
int aps_decode_samples(struct aps_state *state, const int16_t *samples, size_t count,
                        enum aps_origin origin, unsigned metadata_validated,
                        uint32_t now_ms, adda_demod_stats *stats);
void aps_poll(struct aps_state *state, uint32_t now_ms);
int aps_udp_received(struct aps_state *state, uint32_t peer_ipv4, uint16_t peer_port,
                       const uint8_t *bytes, size_t length);
#endif
