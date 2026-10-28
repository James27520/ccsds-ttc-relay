#ifndef RELAY_IQSWAP_H
#define RELAY_IQSWAP_H

/* No UART formatting here: the exact transaction is exercised by native mocks.
 * A toggle changes spectral orientation, never an RF channel selection bit. */
static int diag_iqswap(int tx, int enabled)
{
    uint32_t a0 = 0, a1 = 0, errors = relay_spi_error_count;
    int old, wanted, got, saved_cache;
    unsigned int mask = tx ? PP_TX_SWAP_IQ : PP_RX_SWAP_IQ;
    if (!probe_ready || !ad9361_phy || (tx != 0 && tx != 1) || (enabled != 0 && enabled != 1) ||
        (Xil_In32(R_RELAY_MODE) & 3u) != RELAY_MODE_MUTE)
        goto rejected;
    if (probe_read_atten(0, &a0) || probe_read_atten(1, &a1) ||
        a0 < 30000u || a1 < 30000u || relay_spi_error_count != errors)
        goto rejected;
    old = ad9361_spi_read(ad9361_phy->spi, REG_PARALLEL_PORT_CONF_1);
    if (old < 0 || relay_spi_error_count != errors) goto rejected;
    saved_cache = ad9361_phy->pdata->port_ctrl.pp_conf[0];
    wanted = (old & ~mask) | (enabled ? mask : 0);
    if (ad9361_spi_write(ad9361_phy->spi, REG_PARALLEL_PORT_CONF_1, wanted))
        goto rollback;
    got = ad9361_spi_read(ad9361_phy->spi, REG_PARALLEL_PORT_CONF_1);
    if (got != wanted || relay_spi_error_count != errors) goto rollback;
    ad9361_phy->pdata->port_ctrl.pp_conf[0] =
        (saved_cache & ~mask) | (wanted & mask);
    return 0;
rollback:
    /* The first write may have reached hardware even on a transfer error. */
    ad9361_phy->pdata->port_ctrl.pp_conf[0] = saved_cache;
    relay_set_mode(RELAY_MODE_MUTE);
    if (ad9361_spi_write(ad9361_phy->spi, REG_PARALLEL_PORT_CONF_1, old))
        return -EIO;
    got = ad9361_spi_read(ad9361_phy->spi, REG_PARALLEL_PORT_CONF_1);
    if (got != old) return -EIO;
    return -EIO; /* rolled back; the requested operation still failed */
rejected:
    relay_set_mode(RELAY_MODE_MUTE);
    return -EINVAL;
}
#endif
