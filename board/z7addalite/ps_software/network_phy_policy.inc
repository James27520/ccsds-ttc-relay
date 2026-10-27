/* Board-specific RTL8211E policy inserted into the generated Xilinx port.
 * Uses the vendor advertisement/reset sequence, with checked MDIO and bounded
 * waits. The policy intentionally rejects PHY models not reviewed here.
 * Register 1 is latch-low, so both startup and polling read it twice.
 */
static int adda_phy_read(XEmacPs *mac, u32_t addr, u32_t reg, u16_t *value)
{
    *value = 0;
    if (XEmacPs_PhyRead(mac, addr, reg, value) != XST_SUCCESS) {
        *value = 0;
        return 0;
    }
    return 1;
}

static u32_t adda_phy_current_speed(XEmacPs *mac, u32_t addr)
{
    u16_t id1, id2, status, speed;
    if (!adda_phy_read(mac, addr, 2, &id1) ||
        !adda_phy_read(mac, addr, 3, &id2) ||
        id1 != 0x001CU || (id2 & 0xFFF0U) != 0xC910U)
        return XST_FAILURE;
    if (!adda_phy_read(mac, addr, 1, &status) ||
        !adda_phy_read(mac, addr, 1, &status) ||
        (status & 0x24U) != 0x24U || status == 0xFFFFU)
        return XST_FAILURE;
    if (!adda_phy_read(mac, addr, 0x11U, &speed) || speed == 0xFFFFU ||
        !(speed & 0x0400U)) return XST_FAILURE;
    switch (speed & 0xC000U) {
    case 0x8000U: return 1000;
    case 0x4000U: return 100;
    case 0x0000U: return 10;
    default: return XST_FAILURE;
    }
}

/* Called on an already initialized MAC when the cable returns. No reset,
 * autonegotiation restart or sleep occurs in the cooperative polling path. */
u32_t phy_current_speed_emacps(XEmacPs *mac, u32_t addr)
{
    u32_t speed = adda_phy_current_speed(mac, addr);
    if (speed == 10 || speed == 100 || speed == 1000)
        SetUpSLCRDivisors(mac->Config.BaseAddress, speed);
    return speed;
}

static u32_t get_IEEE_phy_speed(XEmacPs *mac, u32_t addr)
{
    u16_t id1, id2, control, status;
    u32_t poll, speed;
    if (!adda_phy_read(mac, addr, 2, &id1) ||
        !adda_phy_read(mac, addr, 3, &id2)) {
        xil_printf("PHY_ERROR MDIO identity addr=%u\r\n", addr);
        return XST_FAILURE;
    }
    if (id1 != 0x001CU || (id2 & 0xFFF0U) != 0xC910U) {
        xil_printf("PHY_ERROR unsupported addr=%u id=%04x:%04x (requires RTL8211E family)\r\n", addr,id1,id2);
        return XST_FAILURE;
    }
    xil_printf("PHY_IDENT addr=%u id=%04x:%04x; bounded reset=1s autoneg=5s\r\n",addr,id1,id2);
#define ADDA_READ(reg) do { if (!adda_phy_read(mac,addr,(reg),&control)) goto mdio_error; } while (0)
#define ADDA_WRITE(reg) do { if (XEmacPs_PhyWrite(mac,addr,(reg),control)!=XST_SUCCESS) goto mdio_error; } while (0)
    ADDA_READ(IEEE_AUTONEGO_ADVERTISE_REG);
    control |= IEEE_ASYMMETRIC_PAUSE_MASK | IEEE_PAUSE_MASK | ADVERTISE_100 | ADVERTISE_10;
    ADDA_WRITE(IEEE_AUTONEGO_ADVERTISE_REG);
    ADDA_READ(IEEE_1000_ADVERTISE_REG_OFFSET);
    control |= ADVERTISE_1000;
    ADDA_WRITE(IEEE_1000_ADVERTISE_REG_OFFSET);
    ADDA_READ(IEEE_CONTROL_REG_OFFSET);
    control |= IEEE_CTRL_AUTONEGOTIATE_ENABLE | IEEE_STAT_AUTONEGOTIATE_RESTART;
    ADDA_WRITE(IEEE_CONTROL_REG_OFFSET);
    ADDA_READ(IEEE_CONTROL_REG_OFFSET);
    control |= IEEE_CTRL_RESET_MASK;
    ADDA_WRITE(IEEE_CONTROL_REG_OFFSET);
    for (poll=0; poll<1000; ++poll) {
        ADDA_READ(IEEE_CONTROL_REG_OFFSET);
        if (!(control & IEEE_CTRL_RESET_MASK)) break;
        usleep(1000);
    }
    if (poll==1000) {
        xil_printf("PHY_ERROR reset timeout; network down\r\n");
        return XST_FAILURE;
    }
    for (poll=0; poll<500; ++poll) {
        if (!adda_phy_read(mac,addr,1,&status) ||
            !adda_phy_read(mac,addr,1,&status)) goto mdio_error;
        if (status!=0xFFFFU && (status & 0x24U)==0x24U) {
            speed=adda_phy_current_speed(mac,addr);
            if (speed==10 || speed==100 || speed==1000) return speed;
            xil_printf("PHY_ERROR inconsistent speed/link or MDIO; network down\r\n");
            return XST_FAILURE;
        }
        usleep(10000);
    }
    xil_printf("PHY_ERROR no stable link/autoneg timeout; network down, retry network on\r\n");
    return XST_FAILURE;
mdio_error:
    xil_printf("PHY_ERROR MDIO operation; network down\r\n");
    return XST_FAILURE;
#undef ADDA_READ
#undef ADDA_WRITE
}
