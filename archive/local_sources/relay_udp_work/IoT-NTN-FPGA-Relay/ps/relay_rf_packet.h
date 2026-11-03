#ifndef RELAY_RF_PACKET_H
#define RELAY_RF_PACKET_H

#include <stddef.h>
#include <stdint.h>

/* APID 0x101 from rk3588/ccsds.py: 6-byte header, 18-byte data, 2-byte CRC. */
#define RELAY_RF_PACKET_SIZE 26u

struct relay_rf_command {
    uint16_t seq;
    uint64_t rx_hz;
    uint64_t tx_hz;
    uint8_t rx_gain_db;
    uint8_t tx_att_db;
};

static uint16_t relay_be16(const uint8_t *p)
{
    return (uint16_t)(((uint16_t)p[0] << 8) | p[1]);
}

static uint64_t relay_be64(const uint8_t *p)
{
    uint64_t v = 0;
    unsigned i;
    for (i = 0; i < 8; ++i) v = (v << 8) | p[i];
    return v;
}

static uint16_t relay_crc16(const uint8_t *p, size_t n)
{
    uint16_t crc = 0xffffu;
    size_t i;
    unsigned bit;
    for (i = 0; i < n; ++i) {
        crc ^= (uint16_t)p[i] << 8;
        for (bit = 0; bit < 8; ++bit)
            crc = (uint16_t)((crc << 1) ^ ((crc & 0x8000u) ? 0x1021u : 0u));
    }
    return crc;
}

/* Returns 0 only for a complete, valid frequency-control packet. */
static int relay_parse_rf_packet(const uint8_t *p, size_t n,
                                 struct relay_rf_command *out)
{
    uint16_t id, seq;
    if (!p || !out || n != RELAY_RF_PACKET_SIZE) return -1;
    id = relay_be16(p);
    seq = relay_be16(p + 2);
    if (id != 0x0101u || (seq & 0xc000u) != 0xc000u ||
        relay_be16(p + 4) != 17u) return -2;
    if (relay_crc16(p, n - 2) != relay_be16(p + n - 2)) return -3;
    out->seq = seq & 0x3fffu;
    out->rx_hz = relay_be64(p + 6);
    out->tx_hz = relay_be64(p + 14);
    out->rx_gain_db = p[22];
    out->tx_att_db = p[23];
    if (out->rx_hz < 70000000ULL || out->rx_hz > 6000000000ULL ||
        out->tx_hz < 70000000ULL || out->tx_hz > 6000000000ULL ||
        out->rx_gain_db > 76u || out->tx_att_db > 89u) return -4;
    return 0;
}

#endif
