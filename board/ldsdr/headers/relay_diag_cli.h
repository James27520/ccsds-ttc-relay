#ifndef RELAY_DIAG_CLI_H
#define RELAY_DIAG_CLI_H
static void diag_rfdiag(void)
{
    int rc = 0;
    uint32_t before = relay_spi_error_count;
    if (!ad9361_phy) {
        co_s("RFDIAG rc=-19 phy=unavailable"); co_flush();
        cli_last_rc = -ENODEV; return;
    }
    if (probe_print_reg("RFPORT1", REG_PARALLEL_PORT_CONF_1, 0)) rc = -EIO;
    if (probe_print_reg("RFPORT2", REG_PARALLEL_PORT_CONF_2, 0)) rc = -EIO;
    if (probe_print_reg("RFPORT3", REG_PARALLEL_PORT_CONF_3, 0)) rc = -EIO;
    probe_rfread(); /* independent PLLs, PLL locks, gain, attenuation, BIST/loopback */
    if (cli_last_rc || relay_spi_error_count != before) rc = -EIO;
    co_s("RFDIAG_END rc="); co_i(rc);
    co_s(" ready="); co_i(probe_ready);
    co_s(" init_rc="); co_i(probe_init_rc);
    co_s(" spi_errors_total="); co_u(relay_spi_error_count, 0); co_flush();
    cli_last_rc = rc;
}
#endif
