#ifndef RELAY_RF_CONTROL_H
#define RELAY_RF_CONTROL_H

#include "relay_rf_packet.h"

static int relay_frequency_matches(uint64_t actual, uint64_t requested)
{
    return actual > requested ? actual - requested <= 10000ULL
                              : requested - actual <= 10000ULL;
}

/* Call only from the main loop, never from an interrupt handler. */
static int relay_apply_rf_command(const struct relay_rf_command *cmd)
{
    uint64_t old_rx = rx_lo_freq, old_tx = tx_lo_freq;
    uint64_t got_rx = 0, got_tx = 0;
    int old_gain = gain;
    uint32_t old_att = txatt;
    u32 old_mode = Xil_In32(R_RELAY_MODE) & 3u;
    int rc = -1;
    int rollback_ok = 1;

    relay_set_mode(RELAY_MODE_MUTE);
    if (ad9361_set_rx_lo_freq(ad9361_phy, cmd->rx_hz) != 0 ||
        ad9361_set_tx_lo_freq(ad9361_phy, cmd->tx_hz) != 0 ||
        ad9361_get_rx_lo_freq(ad9361_phy, &got_rx) != 0 ||
        ad9361_get_tx_lo_freq(ad9361_phy, &got_tx) != 0 ||
        !relay_frequency_matches(got_rx, cmd->rx_hz) ||
        !relay_frequency_matches(got_tx, cmd->tx_hz) ||
        ad9361_set_rx_rf_gain(ad9361_phy, 0, cmd->rx_gain_db) != 0 ||
        ad9361_set_rx_rf_gain(ad9361_phy, 1, cmd->rx_gain_db) != 0 ||
        ad9361_set_tx_attenuation(ad9361_phy, 0, (uint32_t)cmd->tx_att_db * 1000u) != 0 ||
        ad9361_set_tx_attenuation(ad9361_phy, 1, (uint32_t)cmd->tx_att_db * 1000u) != 0)
        goto restore;

    rx_lo_freq = got_rx;
    tx_lo_freq = got_tx;
    gain = cmd->rx_gain_db;
    txatt = (uint32_t)cmd->tx_att_db * 1000u;
    rc = 0;
    goto done;

restore:
    /* Restore both channels if any part of a multi-register update fails. */
    if (ad9361_set_rx_lo_freq(ad9361_phy, old_rx) != 0) rollback_ok = 0;
    if (ad9361_set_tx_lo_freq(ad9361_phy, old_tx) != 0) rollback_ok = 0;
    if (ad9361_set_rx_rf_gain(ad9361_phy, 0, old_gain) != 0) rollback_ok = 0;
    if (ad9361_set_rx_rf_gain(ad9361_phy, 1, old_gain) != 0) rollback_ok = 0;
    if (ad9361_set_tx_attenuation(ad9361_phy, 0, old_att) != 0) rollback_ok = 0;
    if (ad9361_set_tx_attenuation(ad9361_phy, 1, old_att) != 0) rollback_ok = 0;
done:
    if (rollback_ok) relay_set_mode(old_mode);
    else relay_set_mode(RELAY_MODE_MUTE);
    return rc;
}

#endif
