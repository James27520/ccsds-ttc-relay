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
};
void aps_init(struct aps_state *state, const struct aps_io *io);
void aps_set_network_ready(struct aps_state *state, unsigned ready);
/* Line excludes newline, <=127 characters. status/help/selftest are read-only.
 * nettest RX_MHz TX_MHz SEQ GAIN ATT is an explicit known-command test.
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
