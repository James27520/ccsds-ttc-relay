/* Six-SMA PL: CH2_CTRL holds mode [1:0], Q1.11 gain [13:2], DC enable [14]. */
#ifndef RELAY_DUAL_MODE_H
#define RELAY_DUAL_MODE_H
#define RELAY_CH2_CTRL (R_RELAY_MODE + 0x1cu)
#define RELAY_CH2_FIELDS 0x3fffu

static void relay_dual_set_mode(unsigned mode)
{
    unsigned word;
    if (mode != 1u) mode = 2u;
    if (mode == 2u) relay_set_mode(2u);
    word = Xil_In32(RELAY_CH2_CTRL);
    Xil_Out32(RELAY_CH2_CTRL, (word & ~RELAY_CH2_FIELDS) |
              (RELAY_GAIN_UNITY << 2) | mode);
    if (mode == 1u) relay_set_mode(1u);
}

static int relay_dual_matches(unsigned mode)
{
    return (mode == 1u || mode == 2u) &&
           (Xil_In32(R_RELAY_MODE) & 3u) == mode &&
           (Xil_In32(RELAY_CH2_CTRL) & RELAY_CH2_FIELDS) ==
               ((RELAY_GAIN_UNITY << 2) | mode) &&
           (mode != 1u || (Xil_In32(R_RELAY_GAIN) & 0xfffu) == RELAY_GAIN_UNITY);
}
#endif
