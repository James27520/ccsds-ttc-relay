#ifndef RELAY_PROBE_DIAG_H
#define RELAY_PROBE_DIAG_H

/* Included after CLI output helpers. Reads are SPI-backed, not GUI caches. */
static int probe_read_lo(int tx, uint64_t *value)
{
    uint32_t before = relay_spi_error_count;
    int rc;
    *value = 0;
    if (!ad9361_phy) return -ENODEV;
    rc = tx ? ad9361_get_tx_lo_freq(ad9361_phy, value)
            : ad9361_get_rx_lo_freq(ad9361_phy, value);
    if (relay_spi_error_count != before) { *value = 0; return -EIO; }
    return rc;
}

static int probe_read_gain(unsigned int ch, int32_t *value)
{
    uint32_t before = relay_spi_error_count;
    int rc;
    *value = 0;
    if (!ad9361_phy) return -ENODEV;
    rc = ad9361_get_rx_rf_gain(ad9361_phy, ch, value);
    if (relay_spi_error_count != before) { *value = 0; return -EIO; }
    return rc;
}

static int probe_read_atten(unsigned int ch, uint32_t *value)
{
    uint32_t before = relay_spi_error_count;
    int rc;
    *value = 0;
    if (!ad9361_phy) return -ENODEV;
    rc = ad9361_get_tx_attenuation(ad9361_phy, ch, value);
    if (relay_spi_error_count != before) { *value = 0; return -EIO; }
    return rc;
}

static int probe_radio_check(void)
{
    int rx, tx, bist, loop, dac;
    if (!ad9361_phy) return -ENODEV;
    rx = ad9361_spi_read(ad9361_phy->spi, REG_RX_CP_OVERRANGE_VCO_LOCK);
    tx = ad9361_spi_read(ad9361_phy->spi, REG_TX_CP_OVERRANGE_VCO_LOCK);
    bist = ad9361_spi_read(ad9361_phy->spi, REG_BIST_CONFIG);
    loop = ad9361_spi_read(ad9361_phy->spi, REG_OBSERVE_CONFIG);
    dac = ad9361_spi_read(ad9361_phy->spi, REG_DAC_TEST_2);
    if (rx < 0 || tx < 0 || bist < 0 || loop < 0 || dac < 0) return -EIO;
    if (!(rx & VCO_LOCK) || !(tx & VCO_LOCK)) return -ETIMEDOUT;
    if ((bist & BIST_ENABLE) || (loop & DATA_PORT_LOOP_TEST_ENABLE) ||
        (dac & DAC_TEST_ENABLE)) return -EINVAL;
    return 0;
}

static int probe_close_frequency(uint64_t a, uint64_t b)
{
    return a > b ? a - b <= 10000ULL : b - a <= 10000ULL;
}

static int probe_verify_config(const struct relay_rf_command *cmd)
{
    uint64_t rx = 0, tx = 0;
    uint32_t att0 = 0, att1 = 0;
    int32_t gain0 = 0, gain1 = 0;
    if (!cmd || probe_radio_check() != 0 ||
        probe_read_lo(0, &rx) != 0 || probe_read_lo(1, &tx) != 0 ||
        !probe_close_frequency(rx, cmd->rx_hz) || !probe_close_frequency(tx, cmd->tx_hz) ||
        probe_read_gain(0, &gain0) != 0 || probe_read_gain(1, &gain1) != 0 ||
        probe_read_atten(0, &att0) != 0 || probe_read_atten(1, &att1) != 0 ||
        gain0 != cmd->rx_gain_db || gain1 != cmd->rx_gain_db ||
        att0 != (uint32_t)cmd->tx_att_db * 1000u || att1 != (uint32_t)cmd->tx_att_db * 1000u)
        return -EIO;
    return 0;
}

static void probe_print_value(const char *label, int rc, int value)
{
    co_s(label);
    co_s("_rc="); co_i(rc);
    co_s(" value=");
    if (rc) co_s("NA"); else co_i(value);
}

static int probe_print_reg(const char *label, unsigned int reg, int lock)
{
    int raw = ad9361_spi_read(ad9361_phy->spi, reg);
    co_s(label); co_s(" addr=0x"); co_h(reg, 3);
    co_s(" rc="); co_i(raw < 0 ? raw : 0);
    co_s(" raw=");
    if (raw < 0) co_s("NA"); else { co_s("0x"); co_h(raw, 2); }
    if (lock) {
        co_s(" locked=");
        if (raw < 0) co_s("NA"); else co_u(!!(raw & VCO_LOCK), 0);
    }
    co_flush();
    return raw < 0 ? raw : 0;
}

static void probe_rfread(void)
{
    uint64_t rx = 0, tx = 0;
    uint32_t att0 = 0, att1 = 0, before = relay_spi_error_count;
    int32_t gain0 = 0, gain1 = 0;
    int rr, tr, g0, g1, t0, t1, rc = 0;
    if (!ad9361_phy) {
        co_s("RFREAD rc=-19 phy=unavailable init_failed=1"); co_flush(); return;
    }
    rr = probe_read_lo(0, &rx); tr = probe_read_lo(1, &tx);
    co_s("RFREAD rx_rc="); co_i(rr); co_s(" tx_rc="); co_i(tr);
    co_s(" rx_hz="); if (rr) co_s("NA"); else co_u64(rx);
    co_s(" tx_hz="); if (tr) co_s("NA"); else co_u64(tx);
    co_flush();
    if (rr || tr) rc = -EIO;
    if (probe_print_reg("RFPLL_RX", REG_RX_CP_OVERRANGE_VCO_LOCK, 1)) rc = -EIO;
    if (probe_print_reg("RFPLL_TX", REG_TX_CP_OVERRANGE_VCO_LOCK, 1)) rc = -EIO;
    if (probe_print_reg("RF_PRODUCT_ID", REG_PRODUCT_ID, 0)) rc = -EIO;
    co_s("RF_PRODUCT_ID_NOTE shared_family_register_not_exact_part_identification"); co_flush();
    g0 = probe_read_gain(0, &gain0); g1 = probe_read_gain(1, &gain1);
    t0 = probe_read_atten(0, &att0); t1 = probe_read_atten(1, &att1);
    probe_print_value("RFGAIN rx1_db", g0, gain0); co_s(" ");
    probe_print_value("rx2_db", g1, gain1); co_flush();
    probe_print_value("RFATT tx1_mdB", t0, att0); co_s(" ");
    probe_print_value("tx2_mdB", t1, att1); co_flush();
    if (g0 || g1 || t0 || t1) rc = -EIO;
    if (probe_print_reg("RFBIST", REG_BIST_CONFIG, 0)) rc = -EIO;
    if (probe_print_reg("RFLOOP", REG_OBSERVE_CONFIG, 0)) rc = -EIO;
    if (probe_print_reg("RFPORT_TEST", REG_BIST_AND_DATA_PORT_TEST_CONFIG, 0)) rc = -EIO;
    if (probe_print_reg("RFDAC_TEST", REG_DAC_TEST_2, 0)) rc = -EIO;
    if (relay_spi_error_count != before) rc = -EIO;
    co_s("RFREAD_END rc="); co_i(rc);
    co_s(" spi_errors_total="); co_u(relay_spi_error_count, 0); co_flush();
    cli_last_rc = rc;
}

/* Reject malformed/overflowing numbers before the inherited CLI parser runs. */
static int probe_number_valid(const char *s, int signed_ok)
{
    uint64_t value = 0, limit = 0xffffffffULL;
    unsigned int radix = 10, n = 0;
    if (*s == '-') {
        if (!signed_ok) return 0;
        ++s; limit = 0x7fffffffULL; /* avoid negating INT_MIN in old formatter */
    } else if (signed_ok) limit = 0x7fffffffULL;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) { s += 2; radix = 16; }
    while (*s) {
        unsigned int d;
        if (*s >= '0' && *s <= '9') d = *s - '0';
        else if (*s >= 'a' && *s <= 'f') d = *s - 'a' + 10;
        else if (*s >= 'A' && *s <= 'F') d = *s - 'A' + 10;
        else return 0;
        if (d >= radix) return 0;
        value = value * radix + d;
        if (value > limit) return 0;
        ++n; ++s;
    }
    return n != 0;
}
#endif
