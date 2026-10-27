#include "adda_protocol.h"
/* Include the actual unchanged legacy parser via the compiler include path. */
#include "relay_rf_packet.h"
#include <stdio.h>

int main(void)
{
    uint8_t bytes[AP_RF_BYTES];
    struct relay_rf_command parsed;
    struct ap_command command = {1u,100u,2450u,7u};
    if (ap_rf_packet(&command, 0x123u, 0u, 89u, bytes) != AP_OK ||
        relay_parse_rf_packet(bytes, sizeof(bytes), &parsed) != 0 ||
        parsed.seq != 0x123u || parsed.rx_hz != UINT64_C(100000000) ||
        parsed.tx_hz != UINT64_C(2450000000) || parsed.rx_gain_db != 0u || parsed.tx_att_db != 89u)
        return 1;
    bytes[24] ^= 1u;
    if (relay_parse_rf_packet(bytes, sizeof(bytes), &parsed) != -3) return 2;
    puts("PASS unchanged relay_rf_packet.h accepts exact generated 26B RF_SET and rejects CRC mutation");
    return 0;
}
