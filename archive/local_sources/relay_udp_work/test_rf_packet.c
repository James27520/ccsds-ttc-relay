#include <assert.h>
#include <stdio.h>
#include "IoT-NTN-FPGA-Relay/ps/relay_rf_packet.h"

int main(void)
{
    uint8_t packet[RELAY_RF_PACKET_SIZE] = {
        0x01,0x01,0xc0,0x07,0x00,0x11,0x00,0x00,0x00,0x00,0x35,0xb4,0x2b,
        0x40,0x00,0x00,0x00,0x00,0x3b,0xaa,0x0c,0x40,0x00,0x1e,0x76,0x64
    };
    struct relay_rf_command cmd;
    assert(relay_parse_rf_packet(packet, sizeof(packet), &cmd) == 0);
    assert(cmd.seq == 7 && cmd.rx_hz == 901000000ULL);
    assert(cmd.tx_hz == 1001000000ULL && cmd.rx_gain_db == 0 && cmd.tx_att_db == 30);
    packet[10] ^= 1;
    assert(relay_parse_rf_packet(packet, sizeof(packet), &cmd) == -3);
    packet[10] ^= 1;
    assert(relay_parse_rf_packet(packet, sizeof(packet)-1, &cmd) == -1);
    packet[0] = 0xff;
    assert(relay_parse_rf_packet(packet, sizeof(packet), &cmd) == -2);
    puts("RF_SET parser: PASS");
    return 0;
}
