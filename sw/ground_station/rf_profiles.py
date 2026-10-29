"""Explicit business presets; signal centers include a +0.5 MHz offset.

Legacy points remain available to recorded bench workflows. The three-window
demonstration exposes only the two S-band pairs, not the entire RF chip range.
"""
DEMO_RELAY_PAIRS = ((1989, 2179), (1990, 2180))
LEGACY_RELAY_PAIRS = ((900, 1000), (900, 1001), (901, 1000), (901, 1001))
CONTROL_RELAY_PAIRS = LEGACY_RELAY_PAIRS + DEMO_RELAY_PAIRS
DEMO_TX_CENTERS = tuple(f'{rx}.5' for rx, _ in DEMO_RELAY_PAIRS)
DEMO_RX_CENTERS = tuple(f'{tx}.5' for _, tx in DEMO_RELAY_PAIRS)
BUSINESS_TX_CENTERS = ('900.5', '901.5') + DEMO_TX_CENTERS
BUSINESS_RX_CENTERS = ('1000.5', '1001.5') + DEMO_RX_CENTERS
BUSINESS_TX_LO_HZ = (900000000, 901000000) + tuple(rx*1000000 for rx, _ in DEMO_RELAY_PAIRS)
BUSINESS_RX_LO_HZ = (1000750000, 1001750000) + tuple(tx*1000000+750000 for _, tx in DEMO_RELAY_PAIRS)
DEMO_HINT = '在线方案：1989.5 → 2179.5 或 1990.5 → 2180.5 MHz'


def is_demo_request(request):
    return (type(request) is dict and type(request.get('rx_mhz')) is int and
            type(request.get('tx_mhz')) is int and
            (request['rx_mhz'], request['tx_mhz']) in DEMO_RELAY_PAIRS)
